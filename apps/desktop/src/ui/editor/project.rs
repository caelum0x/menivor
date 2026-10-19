//! Editor project files: open/save a timeline as a `.menivor` project, open a
//! source video directly, and autosave/restore the last editor session.

use std::path::PathBuf;

use gpui::{Context, PathPromptOptions};

use super::{
    create_editor_source_request_id, EditorOverlayFields, EditorSegmentFields, MAX_EDITOR_SEGMENTS,
};
use crate::app_requests::AppRequest;
use crate::media::probe::is_supported_video;
use crate::ui::preview::default_save_directory;
use crate::ui::shell::WorkspaceSection;
use crate::ui::Shell;
use crate::workspace::editor_project::{
    self, EditorProject, ProjectOverlay, ProjectSegment, PROJECT_EXTENSION,
};
use crate::workspace::WorkerCommand;

impl Shell {
    /// Handle a queued app-level request (menu command or OS file open).
    pub(in crate::ui) fn handle_app_request(
        &mut self,
        request: AppRequest,
        cx: &mut Context<Self>,
    ) {
        match request {
            AppRequest::OpenPath(path) => self.open_path(path, cx),
            AppRequest::PromptOpenProject => self.prompt_open_project(cx),
            AppRequest::PromptSaveProject => self.prompt_save_project(cx),
        }
    }

    /// Open a project file or a local source video in the editor.
    pub(in crate::ui) fn open_path(&mut self, path: PathBuf, cx: &mut Context<Self>) {
        if editor_project::is_project_path(&path) {
            match editor_project::load_project(&path) {
                Ok(project) => {
                    if !self.apply_editor_project(project, true, cx) {
                        return;
                    }
                    self.editor_project_path = Some(path.clone());
                    self.state.activity = format!("Opened project {}.", path.display());
                    cx.notify();
                }
                Err(message) => self.fail_editor(message, cx),
            }
        } else if is_supported_video(&path) {
            self.open_editor_source_path(path, true, cx);
        } else {
            self.fail_editor(
                format!(
                    "{} is not a Menivor project (.{PROJECT_EXTENSION}) or a supported video (.mp4, .mov, .webm).",
                    path.display()
                ),
                cx,
            );
        }
    }

    /// Analyze `path` as the editor's local source video.
    pub(in crate::ui) fn open_editor_source_path(
        &mut self,
        path: PathBuf,
        focus_editor: bool,
        cx: &mut Context<Self>,
    ) {
        if focus_editor {
            self.section = WorkspaceSection::Editor;
        }
        let request_id = create_editor_source_request_id();
        self.state.editor_source_request_id = request_id.clone();
        self.state.editor_source_analysis = None;
        self.state.editor_source_activity = "Analyzing local source…".into();
        self.state.operation_error.clear();
        if self
            .worker
            .send(WorkerCommand::AnalyzeEditorSource { request_id, path })
            .is_err()
        {
            self.state.editor_source_activity.clear();
            self.state.operation_error = "The background worker is unavailable.".into();
        }
        cx.notify();
    }

    pub(in crate::ui) fn prompt_open_project(&mut self, cx: &mut Context<Self>) {
        let selected = cx.prompt_for_paths(PathPromptOptions {
            files: true,
            directories: false,
            multiple: false,
            prompt: Some("Open a Menivor project or source video".into()),
        });
        cx.spawn(async move |this, cx| {
            let Ok(Ok(Some(paths))) = selected.await else {
                return;
            };
            let Some(path) = paths.into_iter().next() else {
                return;
            };
            let _ = this.update(cx, |shell, cx| shell.open_path(path, cx));
        })
        .detach();
    }

    /// Save the timeline: straight to the open project file when there is one,
    /// otherwise through the OS save dialog.
    pub(in crate::ui) fn prompt_save_project(&mut self, cx: &mut Context<Self>) {
        if let Some(path) = self.editor_project_path.clone() {
            self.write_editor_project(path, cx);
            return;
        }
        let suggested = self
            .state
            .editor_source_analysis
            .as_ref()
            .and_then(|source| source.path.file_stem())
            .and_then(|stem| stem.to_str())
            .map(|stem| format!("{stem}.{PROJECT_EXTENSION}"))
            .unwrap_or_else(|| format!("Untitled.{PROJECT_EXTENSION}"));
        let selected = cx.prompt_for_new_path(&default_save_directory(), Some(suggested.as_str()));
        cx.spawn(async move |this, cx| {
            let Ok(Ok(Some(path))) = selected.await else {
                return;
            };
            let _ = this.update(cx, |shell, cx| shell.write_editor_project(path, cx));
        })
        .detach();
    }

    fn write_editor_project(&mut self, path: PathBuf, cx: &mut Context<Self>) {
        let path = editor_project::with_project_extension(path);
        let project = self.editor_project_snapshot(cx);
        match editor_project::save_project(&path, &project) {
            Ok(()) => {
                self.state.operation_error.clear();
                self.state.activity = format!("Saved project to {}.", path.display());
                self.editor_project_path = Some(path);
                cx.notify();
            }
            Err(message) => self.fail_editor(message, cx),
        }
    }

    /// Persist the editor session when it changed since the last write, so an
    /// unsaved timeline survives quitting the app.
    pub(in crate::ui) fn autosave_editor_session(&mut self, cx: &mut Context<Self>) {
        let Ok(json) = self.editor_project_snapshot(cx).to_json() else {
            return;
        };
        if json == self.editor_session_saved {
            return;
        }
        if let Err(error) = editor_project::save_session_json(&json) {
            // Report once per distinct session state instead of every tick.
            self.state.activity = format!("Could not autosave the editor timeline: {error}");
            cx.notify();
        }
        self.editor_session_saved = json;
    }

    /// Restore the autosaved editor session on launch without changing section.
    pub(in crate::ui) fn restore_editor_session(&mut self, cx: &mut Context<Self>) {
        let Some(project) = editor_project::load_session() else {
            return;
        };
        if let Ok(json) = project.to_json() {
            self.editor_session_saved = json;
        }
        let _restored = self.apply_editor_project(project, false, cx);
    }

    fn editor_project_snapshot(&self, cx: &Context<Self>) -> EditorProject {
        let segments = self
            .editor_segments
            .iter()
            .map(|fields| ProjectSegment {
                source_in: fields.source_in.read(cx).text(),
                source_out: fields.source_out.read(cx).text(),
                speed: fields.speed.read(cx).text(),
                caption: fields.caption.read(cx).text(),
                effect: fields.effect.read(cx).text(),
            })
            .collect();
        let overlays = self
            .editor_overlays
            .iter()
            .map(|fields| ProjectOverlay {
                text: fields.text.read(cx).text(),
                start: fields.start.read(cx).text(),
                end: fields.end.read(cx).text(),
                position: fields.position.read(cx).text(),
            })
            .collect();
        let source_path = self
            .state
            .editor_source_analysis
            .as_ref()
            .map(|source| source.path.clone());
        EditorProject::new(source_path, segments, overlays)
    }

    fn apply_editor_project(
        &mut self,
        project: EditorProject,
        focus_editor: bool,
        cx: &mut Context<Self>,
    ) -> bool {
        if project.segments.len() > MAX_EDITOR_SEGMENTS {
            self.fail_editor("A timeline can contain at most 200 segments.", cx);
            return false;
        }
        if project.overlays.len() > rf_project::timeline::MAX_OVERLAYS {
            self.fail_editor(
                format!(
                    "A timeline can contain at most {} overlays.",
                    rf_project::timeline::MAX_OVERLAYS
                ),
                cx,
            );
            return false;
        }
        let mut segments = Vec::with_capacity(project.segments.len());
        for segment in &project.segments {
            segments.push(EditorSegmentFields::from_values(
                cx,
                segment.source_in.clone(),
                segment.source_out.clone(),
                segment.speed.clone(),
                segment.caption.clone(),
                segment.effect.clone(),
            ));
        }
        let mut overlays = Vec::with_capacity(project.overlays.len().max(1));
        for overlay in &project.overlays {
            overlays.push(EditorOverlayFields::from_values(
                cx,
                overlay.text.clone(),
                overlay.start.clone(),
                overlay.end.clone(),
                overlay.position.clone(),
            ));
        }
        if overlays.is_empty() {
            overlays.push(EditorOverlayFields::new(cx));
        }
        self.editor_segments = segments;
        self.editor_overlays = overlays;
        self.pending_timeline_export = None;
        if focus_editor {
            self.section = WorkspaceSection::Editor;
        }
        match project.source_path {
            Some(path) if path.is_file() => self.open_editor_source_path(path, focus_editor, cx),
            Some(path) => {
                self.state.editor_source_analysis = None;
                self.state.editor_source_activity = format!(
                    "The project's source video {} is missing. Choose it again to render.",
                    path.display()
                );
                cx.notify();
            }
            None => cx.notify(),
        }
        true
    }
}
