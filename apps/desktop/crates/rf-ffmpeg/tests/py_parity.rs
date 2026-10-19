//! PYTHON-BEHAVIORAL-PARITY tests for `rf-ffmpeg`.
//!
//! These pin the desktop crate's public filtergraph-string output to the exact
//! behavior of the API's `app/services/compose/compose_ffmpeg.py`, so the local
//! render farm emits byte-identical `-filter_complex` nodes to the cloud.
//!
//! Python references pinned here (values verified by running CPython 3):
//!   * `_chroma_filter`        -> `chromakey={color}:{similarity:.4g}:{blend:.4g}`
//!   * `_escape_ass_filter_path` -> normalize `\` to `/`, then backslash-escape
//!     each of `[ ] ; , : '`
//!   * `_build_final_node`     -> `[{in}]ass={esc}:fontsdir={fonts}[final]`
//!   * `_layout_split`         -> `[top][bot]vstack=inputs=2[comp]`
//!
//! NOTE ON SCOPE: the crate's `escape_ass_path` mirrors only the
//! normalize-backslashes + escape-metas half of `_escape_ass_filter_path`. The
//! Python also runs `os.path.abspath(p)` first, which is cwd/OS-dependent and is
//! the caller's responsibility in the desktop port. To keep parity assertions
//! deterministic we feed already-absolute POSIX paths (where `abspath` is a
//! no-op), so the normalize+escape behavior is what's actually compared.

use rf_ffmpeg::{escape_ass_path, FilterGraph};

// --------------------------------------------------------------------------- #
// _chroma_filter parity: `chromakey={color}:{similarity:.4g}:{blend:.4g}`
// --------------------------------------------------------------------------- #

/// Reproduce the Python node exactly for a given color/similarity/blend so we
/// can compare against literals captured from CPython.
fn chroma_node(color: &str, similarity: f64, blend: f64) -> String {
    FilterGraph::new()
        .chromakey("1:v", color, similarity, blend, "keyed")
        .build()
}

#[test]
fn chroma_defaults_match_python_4g() {
    // Python: _chroma_filter({}) -> "chromakey=0x00FF00:0.18:0.1"
    // (defaults color=0x00FF00, similarity=0.18, blend=0.10; 0.10 -> "0.1").
    assert_eq!(
        chroma_node("0x00FF00", 0.18, 0.10),
        "[1:v]chromakey=0x00FF00:0.18:0.1[keyed]"
    );
}

#[test]
fn chroma_trailing_zeros_stripped_like_4g() {
    // format(0.10, '.4g') == "0.1", format(0.50, '.4g') == "0.5",
    // format(1.0, '.4g') == "1" (bare int, no decimal point).
    assert_eq!(
        chroma_node("green", 0.5, 1.0),
        "[1:v]chromakey=green:0.5:1[keyed]"
    );
}

#[test]
fn chroma_rounds_to_four_sig_figs_like_python() {
    // THIS is the divergence the parity suite caught: Rust's default float
    // Display kept full precision ("0.123456"), but Python `.4g` rounds to four
    // significant figures. format(0.123456, '.4g') == "0.1235".
    assert_eq!(
        chroma_node("0x00FF00", 0.123456, 0.33333333),
        "[1:v]chromakey=0x00FF00:0.1235:0.3333[keyed]"
    );
}

#[test]
fn chroma_four_sig_figs_no_rounding_needed() {
    // format(0.9999, '.4g') == "0.9999" (exactly 4 sig figs, untouched).
    // format(0.25, '.4g') == "0.25".
    assert_eq!(
        chroma_node("0x00FF00", 0.9999, 0.25),
        "[1:v]chromakey=0x00FF00:0.9999:0.25[keyed]"
    );
}

#[test]
fn chroma_zero_renders_as_bare_zero() {
    // format(0.0, '.4g') == "0".
    assert_eq!(
        chroma_node("0x00FF00", 0.0, 0.2),
        "[1:v]chromakey=0x00FF00:0:0.2[keyed]"
    );
}

#[test]
fn chroma_exponential_edge_matches_c_printf() {
    // Outside chroma's normal [0,1] range `.4g` switches to `%e` with a
    // two-digit signed exponent, exactly like C printf:
    //   format(1.2345e-05, '.4g') == "1.234e-05"
    //   format(123456.0,   '.4g') == "1.235e+05"
    assert_eq!(
        chroma_node("c", 1.2345e-5, 123456.0),
        "[1:v]chromakey=c:1.234e-05:1.235e+05[keyed]"
    );
}

// --------------------------------------------------------------------------- #
// _escape_ass_filter_path parity: normalize `\`->`/`, escape `[ ] ; , : '`
// --------------------------------------------------------------------------- #

#[test]
fn escape_passes_through_plain_posix_path() {
    // No metacharacters -> identity (abspath is a no-op on an absolute path).
    assert_eq!(escape_ass_path("/tmp/a b/cap.ass"), "/tmp/a b/cap.ass");
}

#[test]
fn escape_normalizes_backslashes_then_escapes_colon() {
    // Windows drive path: `\` -> `/`, then the drive `:` is backslash-escaped.
    // Python (on Windows, where abspath keeps the drive): "C\:/subs/cap.ass".
    assert_eq!(escape_ass_path(r"C:\subs\cap.ass"), r"C\:/subs/cap.ass");
}

#[test]
fn escape_each_structural_meta_is_backslash_prefixed() {
    // Python escapes exactly `[ ] ; , : '` in that pass. Given input a[b];c,d'e:
    //   -> a\[b\]\;c\,d\'e
    assert_eq!(escape_ass_path("a[b];c,d'e"), r"a\[b\]\;c\,d\'e");
}

#[test]
fn escape_backslash_before_meta_normalizes_first_no_double_escape() {
    // A literal backslash is turned into `/` BEFORE meta-escaping, so a
    // `\:` sequence in the input does not survive as a doubled escape.
    // Python: "\\:" -> abspath/replace -> "/:" -> escape ":" -> "/\:".
    // We feed an absolute-ish path so only the normalize+escape is compared.
    assert_eq!(escape_ass_path("/a\\:b"), r"/a/\:b");
}

#[test]
fn escape_apostrophe_in_directory_name() {
    // Single quote is a filtergraph quote char and must be escaped.
    assert_eq!(
        escape_ass_path("/home/o'brien/cap.ass"),
        r"/home/o\'brien/cap.ass"
    );
}

// --------------------------------------------------------------------------- #
// _build_final_node parity: `[{in}]ass={esc}:fontsdir={fonts}[final]`
// --------------------------------------------------------------------------- #

#[test]
fn ass_burn_node_shape_matches_build_final_node() {
    // Python `_build_final_node` emits: [comp]ass={esc}:fontsdir={fonts}[final]
    // with BOTH the subtitle path and the fonts dir escaped identically.
    let s = FilterGraph::new()
        .ass("comp", "/subs/cap.ass", "/fonts", "final")
        .build();
    assert_eq!(s, "[comp]ass=/subs/cap.ass:fontsdir=/fonts[final]");
}

#[test]
fn ass_burn_escapes_both_operands() {
    // A colon inside the subtitle path (Windows drive) is escaped so it does not
    // read as an `ass=` option separator; the fonts dir is escaped the same way.
    let s = FilterGraph::new()
        .ass("comp", r"C:\s\cap.ass", r"C:\fonts", "final")
        .build();
    assert_eq!(s, r"[comp]ass=C\:/s/cap.ass:fontsdir=C\:/fonts[final]");
}

// --------------------------------------------------------------------------- #
// _layout_split parity: `[top][bot]vstack=inputs=2[comp]`
// --------------------------------------------------------------------------- #

#[test]
fn vstack_matches_layout_split_terminal_node() {
    // The final node of `_layout_split` is literally this string.
    let s = FilterGraph::new().vstack("top", "bot", "comp").build();
    assert_eq!(s, "[top][bot]vstack=inputs=2[comp]");
}

#[test]
fn vstack_always_declares_inputs_2() {
    // `vstack=inputs=2` is fixed by the two-input stack contract regardless of
    // the labels chosen.
    let s = FilterGraph::new()
        .vstack("screen_top", "avatar_bot", "stacked")
        .build();
    assert!(s.contains("vstack=inputs=2"));
    assert_eq!(s, "[screen_top][avatar_bot]vstack=inputs=2[stacked]");
}

// --------------------------------------------------------------------------- #
// End-to-end: a chroma+overlay+ass chain composed via the public builder.
// --------------------------------------------------------------------------- #

#[test]
fn full_greenscreen_chain_composes_like_the_api() {
    let s = FilterGraph::new()
        .scale_crop_fill("0:v", 1080, 1920, "bg")
        .chromakey("1:v", "0x00FF00", 0.18, 0.10, "fg")
        .overlay("bg", "fg", 0, 0, "comp")
        .ass("comp", "/subs/karaoke.ass", "/fonts", "final")
        .build();
    assert_eq!(
        s,
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920[bg];\
         [1:v]chromakey=0x00FF00:0.18:0.1[fg];\
         [bg][fg]overlay=0:0[comp];\
         [comp]ass=/subs/karaoke.ass:fontsdir=/fonts[final]"
    );
}
