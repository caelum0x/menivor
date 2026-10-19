//! Top-level GPUI composition for the native Menivor desktop app: the app menu,
//! global commands (quit, hide, open/save project), OS file-open requests, and
//! the single workspace window.

use gpui::{
    actions, px, size, App, AppContext, Application, Bounds, KeyBinding, Menu, MenuItem, OsAction,
    SharedString, TitlebarOptions, WindowBounds, WindowOptions,
};

use crate::app_requests::{self, AppRequest};
use crate::config::DEFAULT_WEB_ORIGIN;
use crate::ui::components::{bind_text_field_keys, CopyText, CutText, PasteText, SelectAllText};
use crate::ui::Shell;

/// User-facing product name (window title, app menu).
pub(crate) const PRODUCT_NAME: &str = "Menivor";

actions!(
    menivor,
    [
        Quit,
        Hide,
        HideOthers,
        ShowAll,
        OpenProject,
        SaveProject,
        OpenWebsite,
        ManageApiKeys,
    ]
);

pub(crate) fn run() {
    // Files named on the command line ("Open With" on Linux passes `%U`).
    app_requests::queue_launch_arguments();

    let application = Application::new();
    // macOS "Open With", Finder double-clicks and Dock drops arrive as URLs.
    application.on_open_urls(app_requests::queue_open_urls);
    application.run(|cx: &mut App| {
        bind_text_field_keys(cx);
        register_app_commands(cx);
        cx.set_menus(app_menus());

        let bounds = Bounds::centered(None, size(px(960.), px(600.)), cx);
        cx.open_window(
            WindowOptions {
                titlebar: Some(TitlebarOptions {
                    title: Some(SharedString::from(PRODUCT_NAME)),
                    ..Default::default()
                }),
                window_bounds: Some(WindowBounds::Maximized(bounds)),
                ..Default::default()
            },
            |window, cx| {
                cx.new(|cx| {
                    cx.observe_window_appearance(window, |_, window, _| {
                        window.refresh();
                    })
                    .detach();
                    Shell::new(cx)
                })
            },
        )
        .expect("failed to open the main window");

        // Single-window app: closing the workspace window ends the session, so
        // the process never lingers with no window and no way back in.
        cx.on_window_closed(|cx| {
            if cx.windows().is_empty() {
                cx.quit();
            }
        })
        .detach();
        cx.activate(true);
    });
}

fn register_app_commands(cx: &mut App) {
    cx.on_action(|_: &Quit, cx: &mut App| cx.quit());
    cx.on_action(|_: &Hide, cx: &mut App| cx.hide());
    cx.on_action(|_: &HideOthers, cx: &mut App| cx.hide_other_apps());
    cx.on_action(|_: &ShowAll, cx: &mut App| cx.unhide_other_apps());
    cx.on_action(|_: &OpenProject, _cx: &mut App| {
        app_requests::push(AppRequest::PromptOpenProject)
    });
    cx.on_action(|_: &SaveProject, _cx: &mut App| {
        app_requests::push(AppRequest::PromptSaveProject)
    });
    cx.on_action(|_: &OpenWebsite, cx: &mut App| cx.open_url(DEFAULT_WEB_ORIGIN));
    cx.on_action(|_: &ManageApiKeys, cx: &mut App| {
        cx.open_url(&format!("{DEFAULT_WEB_ORIGIN}/account/api-keys"))
    });

    #[cfg(target_os = "macos")]
    cx.bind_keys([
        KeyBinding::new("cmd-q", Quit, None),
        KeyBinding::new("cmd-h", Hide, None),
        KeyBinding::new("alt-cmd-h", HideOthers, None),
        KeyBinding::new("cmd-o", OpenProject, None),
        KeyBinding::new("cmd-s", SaveProject, None),
    ]);
    #[cfg(not(target_os = "macos"))]
    cx.bind_keys([
        KeyBinding::new("ctrl-q", Quit, None),
        KeyBinding::new("ctrl-o", OpenProject, None),
        KeyBinding::new("ctrl-s", SaveProject, None),
    ]);
}

fn app_menus() -> Vec<Menu> {
    vec![
        Menu {
            name: PRODUCT_NAME.into(),
            items: vec![
                MenuItem::action("Visit menivor.com", OpenWebsite),
                MenuItem::separator(),
                MenuItem::action("Hide Menivor", Hide),
                MenuItem::action("Hide Others", HideOthers),
                MenuItem::action("Show All", ShowAll),
                MenuItem::separator(),
                MenuItem::action("Quit Menivor", Quit),
            ],
        },
        Menu {
            name: "File".into(),
            items: vec![
                MenuItem::action("Open Project or Video…", OpenProject),
                MenuItem::action("Save Project…", SaveProject),
            ],
        },
        Menu {
            name: "Edit".into(),
            items: vec![
                MenuItem::os_action("Cut", CutText, OsAction::Cut),
                MenuItem::os_action("Copy", CopyText, OsAction::Copy),
                MenuItem::os_action("Paste", PasteText, OsAction::Paste),
                MenuItem::separator(),
                MenuItem::os_action("Select All", SelectAllText, OsAction::SelectAll),
            ],
        },
        Menu {
            name: "Help".into(),
            items: vec![MenuItem::action("Manage API Keys", ManageApiKeys)],
        },
    ]
}
