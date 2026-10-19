//! Operational non-destructive timeline editor actions.

mod project;

use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

use gpui::{AppContext, Context, Entity, PathPromptOptions, Window};
use rf_project::{Overlay, OverlayPosition, Segment, TimelineExport};

use crate::ui::components::TextField;
use crate::ui::shell::WorkspaceSection;
use crate::ui::Shell;
use crate::workspace::{JobKind, JobState, LocalRenderRequest, WorkerCommand};

static EDITOR_SEQUENCE: AtomicU64 = AtomicU64::new(1);
const MAX_EDITOR_SEGMENTS: usize = 200;

pub(super) struct EditorSegmentFields {
    pub source_in: Entity<TextField>,
    pub source_out: Entity<TextField>,
    pub speed: Entity<TextField>,
    pub caption: Entity<TextField>,
    /// Animation effect kernel id applied to this segment (blank = none). The
    /// Effects section writes into this field so the selection persists onto the
    /// `Segment` model and survives compose/export.
    pub effect: Entity<TextField>,
}

impl EditorSegmentFields {
    pub fn new(cx: &mut Context<Shell>, index: usize) -> Self {
        let (source_in, source_out) = next_segment_window(index);
        Self::from_values(
            cx,
            source_in.to_string(),
            source_out.to_string(),
            "1".into(),
            String::new(),
            String::new(),
        )
    }

    fn from_values(
        cx: &mut Context<Shell>,
        source_in: String,
        source_out: String,
        speed: String,
        caption: String,
        effect: String,
    ) -> Self {
        Self {
            source_in: cx.new(|cx| TextField::new(cx, source_in, "Source in (seconds)", false)),
            source_out: cx.new(|cx| TextField::new(cx, source_out, "Source out (seconds)", false)),
            speed: cx.new(|cx| TextField::new(cx, speed, "Speed (0.25–4)", false)),
            caption: cx.new(|cx| TextField::new(cx, caption, "Segment caption (optional)", false)),
            effect: cx.new(|cx| TextField::new(cx, effect, effect_placeholder(), false)),
        }
    }

    fn duplicate(&self, cx: &mut Context<Shell>) -> Self {
        Self::from_values(
            cx,
            self.source_in.read(cx).text(),
            self.source_out.read(cx).text(),
            self.speed.read(cx).text(),
            self.caption.read(cx).text(),
            self.effect.read(cx).text(),
        )
    }

    fn segment(&self, index: usize, cx: &Context<Shell>) -> Result<Segment, String> {
        Ok(Segment {
            source_in_ms: parse_decimal_scaled(
                &self.source_in.read(cx).text(),
                &format!("Segment {} source in", index + 1),
                1000,
                21_600_000,
            )?,
            source_out_ms: parse_decimal_scaled(
                &self.source_out.read(cx).text(),
                &format!("Segment {} source out", index + 1),
                1000,
                21_600_000,
            )?,
            speed_milli: parse_decimal_scaled(
                &self.speed.read(cx).text(),
                &format!("Segment {} speed", index + 1),
                1000,
                4000,
            )?,
            caption: self.caption.read(cx).text().trim().to_owned(),
            effect_kernel: parse_effect_kernel(
                &self.effect.read(cx).text(),
                &format!("Segment {} effect", index + 1),
            )?,
        })
    }
}

pub(super) struct EditorOverlayFields {
    pub text: Entity<TextField>,
    pub start: Entity<TextField>,
    pub end: Entity<TextField>,
    pub position: Entity<TextField>,
}

impl EditorOverlayFields {
    pub fn new(cx: &mut Context<Shell>) -> Self {
        Self::from_values(cx, String::new(), "0".into(), "3".into(), "bottom".into())
    }

    fn from_values(
        cx: &mut Context<Shell>,
        text: String,
        start: String,
        end: String,
        position: String,
    ) -> Self {
        Self {
            text: cx.new(|cx| TextField::new(cx, text, "Overlay text", false)),
            start: cx.new(|cx| TextField::new(cx, start, "Start (seconds)", false)),
            end: cx.new(|cx| TextField::new(cx, end, "End (seconds)", false)),
            position: cx.new(|cx| TextField::new(cx, position, "top, center, or bottom", false)),
        }
    }

    fn overlay(&self, index: usize, cx: &Context<Shell>) -> Result<Option<Overlay>, String> {
        let text = self.text.read(cx).text().trim().to_owned();
        if text.is_empty() {
            return Ok(None);
        }
        let start_ms = parse_decimal_scaled(
            &self.start.read(cx).text(),
            &format!("Overlay {} start", index + 1),
            1000,
            21_600_000,
        )?;
        let end_ms = parse_decimal_scaled(
            &self.end.read(cx).text(),
            &format!("Overlay {} end", index + 1),
            1000,
            21_600_000,
        )?;
        let position = match self
            .position
            .read(cx)
            .text()
            .trim()
            .to_ascii_lowercase()
            .as_str()
        {
            "top" => OverlayPosition::Top,
            "center" => OverlayPosition::Center,
            "bottom" => OverlayPosition::Bottom,
            _ => {
                return Err(format!(
                    "Overlay {} position must be top, center, or bottom.",
                    index + 1
                ))
            }
        };
        Ok(Some(Overlay {
            text,
            start_ms,
            end_ms,
            position,
        }))
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(super) struct PendingTimelineExport {
    pub source_job_id: String,
    pub timeline: TimelineExport,
    pub idempotency_key: String,
}

impl Shell {
    pub(in crate::ui) fn choose_editor_source(
        &mut self,
        _window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let selected = cx.prompt_for_paths(PathPromptOptions {
            files: true,
            directories: false,
            multiple: false,
            prompt: Some("Choose the local source video to analyze".into()),
        });
        let commands = self.worker.clone();
        let request_id = create_editor_source_request_id();
        cx.spawn(async move |this, cx| {
            let Ok(Ok(Some(paths))) = selected.await else {
                return;
            };
            let Some(path) = paths.into_iter().next() else {
                return;
            };
            let request_id_for_state = request_id.clone();
            let _ = this.update(cx, |shell, cx| {
                shell.state.editor_source_request_id = request_id_for_state;
                shell.state.editor_source_analysis = None;
                shell.state.editor_source_activity = "Analyzing local source…".into();
                shell.state.operation_error.clear();
                cx.notify();
            });
            if commands
                .send(WorkerCommand::AnalyzeEditorSource { request_id, path })
                .is_err()
            {
                let _ = this.update(cx, |shell, cx| {
                    shell.state.editor_source_activity.clear();
                    shell.state.operation_error = "The background worker is unavailable.".into();
                    cx.notify();
                });
            }
        })
        .detach();
    }

    pub(in crate::ui) fn choose_local_timeline_render(
        &mut self,
        _window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        if !self.state.local_runtime_ready {
            self.fail_editor("The durable local executor is unavailable.", cx);
            return;
        }
        let timeline = match self.timeline_from_fields(cx) {
            Ok(timeline) => timeline,
            Err(message) => {
                self.fail_editor(message, cx);
                return;
            }
        };
        if let Err(error) = timeline.validate() {
            self.fail_editor(format!("Timeline is not renderable: {error}."), cx);
            return;
        }
        let Some(source) = self.state.editor_source_analysis.clone() else {
            self.fail_editor("Analyze a local source before rendering this timeline.", cx);
            return;
        };
        if let Err(message) = validate_timeline_within_source(&timeline, source.duration_ms) {
            self.fail_editor(message, cx);
            return;
        }
        let request = LocalRenderRequest {
            task_id: create_local_timeline_task_id(),
            input_path: source.path,
            expected_source_sha256: Some(source.source_sha256),
            timeline: Some(timeline),
        };
        if self
            .worker
            .send(WorkerCommand::SubmitLocalRender(request))
            .is_err()
        {
            self.fail_editor("The background worker is unavailable.", cx);
            return;
        }
        self.state.local_execution_activity =
            "Staging the analyzed timeline source before durable scheduling…".into();
        self.state.local_execution_failed = false;
        self.state.operation_error.clear();
        cx.notify();
    }

    pub(in crate::ui) fn add_editor_segment(&mut self, cx: &mut Context<Self>) {
        if self.editor_segments.len() >= MAX_EDITOR_SEGMENTS {
            self.fail_editor("A timeline can contain at most 200 segments.", cx);
            return;
        }
        self.editor_segments
            .push(EditorSegmentFields::new(cx, self.editor_segments.len()));
        self.pending_timeline_export = None;
        self.state.operation_error.clear();
        cx.notify();
    }

    pub(in crate::ui) fn remove_editor_segment_at(&mut self, index: usize, cx: &mut Context<Self>) {
        if self.editor_segments.len() == 1 {
            self.fail_editor("A timeline needs at least one segment.", cx);
            return;
        }
        if index < self.editor_segments.len() {
            self.editor_segments.remove(index);
            self.finish_editor_mutation(cx);
        }
    }

    pub(in crate::ui) fn duplicate_editor_segment(&mut self, index: usize, cx: &mut Context<Self>) {
        if self.editor_segments.len() >= MAX_EDITOR_SEGMENTS {
            self.fail_editor("A timeline can contain at most 200 segments.", cx);
            return;
        }
        if let Some(fields) = self.editor_segments.get(index) {
            let duplicate = fields.duplicate(cx);
            self.editor_segments.insert(index + 1, duplicate);
            self.finish_editor_mutation(cx);
        }
    }

    pub(in crate::ui) fn move_editor_segment(
        &mut self,
        index: usize,
        direction: isize,
        cx: &mut Context<Self>,
    ) {
        let destination = index.checked_add_signed(direction);
        if let Some(destination) = destination.filter(|value| *value < self.editor_segments.len()) {
            self.editor_segments.swap(index, destination);
            self.finish_editor_mutation(cx);
        }
    }

    pub(in crate::ui) fn add_editor_overlay(&mut self, cx: &mut Context<Self>) {
        if self.editor_overlays.len() >= rf_project::timeline::MAX_OVERLAYS {
            self.fail_editor("A timeline can contain at most 50 overlays.", cx);
            return;
        }
        self.editor_overlays.push(EditorOverlayFields::new(cx));
        self.finish_editor_mutation(cx);
    }

    /// Effects section → editor bridge: write the selected effect kernel onto a
    /// specific timeline segment so the choice persists on the `Segment` model
    /// and survives compose/export. Rejects unknown kernels and out-of-range
    /// targets, then focuses the editor on the segment it just changed.
    pub(in crate::ui) fn apply_effect_to_segment(
        &mut self,
        segment_index: usize,
        kernel_id: String,
        cx: &mut Context<Self>,
    ) {
        if rf_effects::category_of(&kernel_id).is_none() {
            self.fail_editor(
                format!("Effect kernel \"{kernel_id}\" is not a known effect kernel."),
                cx,
            );
            return;
        }
        let Some(fields) = self.editor_segments.get(segment_index) else {
            self.fail_editor(
                format!("Segment {} is no longer on the timeline.", segment_index + 1),
                cx,
            );
            return;
        };
        let effect_field = fields.effect.clone();
        effect_field.update(cx, |field, cx| field.set_text(kernel_id.clone(), cx));
        // A changed segment invalidates any in-flight export idempotency key.
        self.pending_timeline_export = None;
        self.section = WorkspaceSection::Editor;
        self.state.operation_error.clear();
        self.state.activity = format!(
            "Applied effect {kernel_id} to segment {} — it exports with the timeline.",
            segment_index + 1
        );
        cx.notify();
    }

    pub(in crate::ui) fn remove_editor_overlay(&mut self, index: usize, cx: &mut Context<Self>) {
        if index < self.editor_overlays.len() {
            self.editor_overlays.remove(index);
            self.finish_editor_mutation(cx);
        }
    }

    pub(in crate::ui) fn submit_timeline_export(&mut self, cx: &mut Context<Self>) {
        let Some(source) = self.state.selected_job().cloned() else {
            self.fail_editor("Select a completed reel from the library first.", cx);
            return;
        };
        if source.kind != JobKind::Reel || source.state != JobState::Complete {
            self.fail_editor("Timeline export needs a completed reel.", cx);
            return;
        }

        let timeline = match self.timeline_from_fields(cx) {
            Ok(timeline) => timeline,
            Err(message) => {
                self.fail_editor(message, cx);
                return;
            }
        };
        if let Err(error) = timeline.validate() {
            self.fail_editor(format!("Timeline is not exportable: {error}."), cx);
            return;
        }

        let idempotency_key = match self.pending_timeline_export.as_ref() {
            Some(pending) if pending.source_job_id == source.id && pending.timeline == timeline => {
                pending.idempotency_key.clone()
            }
            _ => {
                let key = create_editor_idempotency_key();
                self.pending_timeline_export = Some(PendingTimelineExport {
                    source_job_id: source.id.clone(),
                    timeline: timeline.clone(),
                    idempotency_key: key.clone(),
                });
                key
            }
        };

        if self
            .worker
            .send(WorkerCommand::SubmitTimelineExport {
                source_job_id: source.id,
                timeline,
                idempotency_key,
            })
            .is_err()
        {
            self.fail_editor("The background worker is unavailable.", cx);
            return;
        }
        self.state.activity = "Submitting timeline export…".into();
        self.state.operation_error.clear();
        cx.notify();
    }

    fn timeline_from_fields(&self, cx: &Context<Self>) -> Result<TimelineExport, String> {
        let segments = self
            .editor_segments
            .iter()
            .enumerate()
            .map(|(index, fields)| fields.segment(index, cx))
            .collect::<Result<Vec<_>, _>>()?;
        let overlays = self
            .editor_overlays
            .iter()
            .enumerate()
            .map(|(index, fields)| fields.overlay(index, cx))
            .collect::<Result<Vec<_>, _>>()?
            .into_iter()
            .flatten()
            .collect();
        Ok(TimelineExport { segments, overlays })
    }

    fn fail_editor(&mut self, message: impl Into<String>, cx: &mut Context<Self>) {
        self.state.activity.clear();
        self.state.operation_error = message.into();
        cx.notify();
    }

    fn finish_editor_mutation(&mut self, cx: &mut Context<Self>) {
        self.pending_timeline_export = None;
        self.state.operation_error.clear();
        cx.notify();
    }
}

/// Validate a segment's effect-kernel field into the `Segment::effect_kernel`
/// slot. A blank field means "no effect" (`None`); a non-blank value must name a
/// kernel the `rf-effects` registry actually knows, so an unknown id is rejected
/// at the boundary rather than silently exported to a backend that can't render
/// it. `rf-project` deliberately stays effects-agnostic, so the registry check
/// lives here where the UI already owns `rf-effects`.
/// Placeholder that names the effects a segment accepts, so nobody has to
/// guess a kernel id.
fn effect_placeholder() -> String {
    let kernels = rf_effects::list_kernels(None);
    if kernels.is_empty() {
        "Effect (optional)".to_owned()
    } else {
        format!("Effect (optional): {}", kernels.join(", "))
    }
}

fn parse_effect_kernel(input: &str, label: &str) -> Result<Option<String>, String> {
    let trimmed = input.trim();
    if trimmed.is_empty() {
        return Ok(None);
    }
    if trimmed.chars().count() > rf_project::timeline::MAX_EFFECT_KERNEL_CHARS {
        return Err(format!(
            "{label} is too long (max {} characters).",
            rf_project::timeline::MAX_EFFECT_KERNEL_CHARS
        ));
    }
    if rf_effects::category_of(trimmed).is_none() {
        return Err(format!(
            "{label} \"{trimmed}\" is not a known effect. Use one of: {}.",
            rf_effects::list_kernels(None).join(", ")
        ));
    }
    Ok(Some(trimmed.to_owned()))
}

/// Parse a plain decimal into a scaled integer without binary floating point.
fn parse_decimal_scaled(input: &str, label: &str, scale: u32, maximum: u32) -> Result<u32, String> {
    let input = input.trim();
    if input.is_empty() || input.starts_with('-') || input.starts_with('+') {
        return Err(format!("{label} must be a non-negative decimal."));
    }
    let mut parts = input.split('.');
    let whole = parts.next().unwrap_or_default();
    let fraction = parts.next();
    if parts.next().is_some()
        || whole.is_empty()
        || !whole.bytes().all(|byte| byte.is_ascii_digit())
        || fraction.is_some_and(|value| {
            value.is_empty() || value.len() > 3 || !value.bytes().all(|byte| byte.is_ascii_digit())
        })
    {
        return Err(format!("{label} must use at most three decimal places."));
    }
    let whole: u64 = whole
        .parse()
        .map_err(|_| format!("{label} is too large."))?;
    let fractional = fraction.unwrap_or("");
    let fraction_value = if fractional.is_empty() {
        0
    } else {
        fractional
            .parse::<u64>()
            .map_err(|_| format!("{label} is not a decimal."))?
            * 10_u64.pow(3 - fractional.len() as u32)
    };
    let value_at_thousand = whole
        .checked_mul(1000)
        .and_then(|value| value.checked_add(fraction_value))
        .ok_or_else(|| format!("{label} is too large."))?;
    let scaled = value_at_thousand
        .checked_mul(scale as u64)
        .map(|value| value / 1000)
        .ok_or_else(|| format!("{label} is too large."))?;
    if scaled > maximum as u64 {
        return Err(format!("{label} exceeds the supported maximum."));
    }
    Ok(scaled as u32)
}

fn create_editor_idempotency_key() -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    let sequence = EDITOR_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    format!("desktop-editor-{}-{nanos}-{sequence}", std::process::id())
}

fn create_local_timeline_task_id() -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    let sequence = EDITOR_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    format!("local-timeline-{nanos}-{sequence}")
}

fn create_editor_source_request_id() -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    let sequence = EDITOR_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    format!("editor-source-{nanos}-{sequence}")
}

fn validate_timeline_within_source(
    timeline: &TimelineExport,
    source_duration_ms: u64,
) -> Result<(), String> {
    if let Some((index, segment)) = timeline
        .segments
        .iter()
        .enumerate()
        .find(|(_, segment)| u64::from(segment.source_out_ms) > source_duration_ms)
    {
        return Err(format!(
            "Segment {} ends at {:.3}s, beyond the analyzed source duration of {:.3}s.",
            index + 1,
            segment.source_out_ms as f64 / 1000.0,
            source_duration_ms as f64 / 1000.0
        ));
    }
    Ok(())
}

fn next_segment_window(index: usize) -> (u32, u32) {
    let start = (index as u32).saturating_mul(15).min(21_599);
    (start, (start + 15).min(21_600))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn decimal_parser_is_exact_at_millisecond_precision() {
        assert_eq!(
            parse_decimal_scaled("12.345", "Time", 1000, u32::MAX),
            Ok(12_345)
        );
        assert_eq!(parse_decimal_scaled("0.25", "Speed", 1000, 4000), Ok(250));
        assert_eq!(parse_decimal_scaled("4", "Speed", 1000, 4000), Ok(4000));
    }

    #[test]
    fn decimal_parser_rejects_lossy_or_unsafe_input() {
        assert!(parse_decimal_scaled("1.0001", "Time", 1000, u32::MAX).is_err());
        assert!(parse_decimal_scaled("-1", "Time", 1000, u32::MAX).is_err());
        assert!(parse_decimal_scaled("1e3", "Time", 1000, u32::MAX).is_err());
        assert!(parse_decimal_scaled("4.001", "Speed", 1000, 4000).is_err());
    }

    #[test]
    fn new_segment_windows_are_ordered_and_stay_within_backend_bounds() {
        assert_eq!(next_segment_window(0), (0, 15));
        assert_eq!(next_segment_window(1), (15, 30));
        assert_eq!(next_segment_window(199), (2985, 3000));
        assert_eq!(next_segment_window(usize::MAX), (21_599, 21_600));
    }

    #[test]
    fn effect_kernel_parses_known_ids_and_rejects_unknown() {
        // A known registry id (with surrounding whitespace) resolves and trims.
        assert_eq!(
            parse_effect_kernel("  shake  ", "Segment 1 effect"),
            Ok(Some("shake".to_owned()))
        );
        // Blank means "no effect".
        assert_eq!(parse_effect_kernel("   ", "Segment 1 effect"), Ok(None));
        // An id the registry does not know is refused at the boundary.
        assert!(parse_effect_kernel("not-a-kernel", "Segment 1 effect").is_err());
    }

    #[test]
    fn effect_kernel_rejects_overlong_id() {
        let long = "k".repeat(rf_project::timeline::MAX_EFFECT_KERNEL_CHARS + 1);
        assert!(parse_effect_kernel(&long, "Segment 1 effect").is_err());
    }

    #[test]
    fn local_timeline_cannot_read_past_analyzed_source() {
        let timeline = TimelineExport {
            segments: vec![Segment::new(250, 1_001)],
            overlays: vec![],
        };
        assert!(validate_timeline_within_source(&timeline, 1_000)
            .unwrap_err()
            .contains("Segment 1"));
        assert!(validate_timeline_within_source(&timeline, 1_001).is_ok());
    }
}
