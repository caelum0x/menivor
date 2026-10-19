//! ffmpeg filtergraph builder (`rf-ffmpeg`) — the desktop mirror of the API's
//! compose filtergraph concepts (scale-to-fill, crop, overlay, chroma-key,
//! caption burn, split-screen stacks). Builds a `-filter_complex` string
//! node-by-node with stable labels so the local render farm composes identically
//! to the cloud (`app/services/compose/compose_ffmpeg.py`). Pure string assembly.

/// Escape a path for an `ass=`/`subtitles=` filtergraph argument, mirroring the
/// API's `_escape_ass_filter_path`: normalize backslashes to forward slashes, then
/// backslash-escape every filtergraph-special char (`[ ] ; , : '`) so libass
/// receives one intact filename regardless of platform.
pub fn escape_ass_path(path: &str) -> String {
    let normalized = path.replace('\\', "/");
    let mut out = String::with_capacity(normalized.len() + 8);
    for ch in normalized.chars() {
        if matches!(ch, '[' | ']' | ';' | ',' | ':' | '\'') {
            out.push('\\');
        }
        out.push(ch);
    }
    out
}

/// Strip a fixed-notation number the way C/`printf` `%g` does: drop trailing
/// zeros in the fractional part and a bare trailing decimal point.
fn strip_fixed_zeros(mut s: String) -> String {
    if s.contains('.') {
        while s.ends_with('0') {
            s.pop();
        }
        if s.ends_with('.') {
            s.pop();
        }
    }
    s
}

/// Format `v` exactly like Python/C `format(v, ".{precision}g")` (`%.<p>g`):
/// `precision` significant digits, `%f` style when the decimal exponent is in
/// `[-4, precision)` else `%e` style, with trailing zeros stripped and the
/// exponent rendered as `e±NN` (min two digits). This is what the API's
/// `_chroma_filter` relies on via `{similarity:.4g}:{blend:.4g}`.
fn fmt_g(v: f64, precision: usize) -> String {
    if v == 0.0 {
        return "0".to_string();
    }
    let p = precision.max(1);
    // Rounded scientific form gives the true `%g` decimal exponent robustly.
    let sci = format!("{:.*e}", p - 1, v);
    let epos = sci.find('e').expect("scientific format always has 'e'");
    let exp: i32 = sci[epos + 1..]
        .parse()
        .expect("scientific exponent is an integer");
    if exp >= -4 && exp < p as i32 {
        let decimals = (p as i32 - 1 - exp).max(0) as usize;
        strip_fixed_zeros(format!("{:.*}", decimals, v))
    } else {
        let mantissa = strip_fixed_zeros(sci[..epos].to_string());
        let sign = if exp < 0 { '-' } else { '+' };
        format!("{}e{}{:02}", mantissa, sign, exp.abs())
    }
}

/// Format a chroma tuning constant exactly the way the API's `%.4g` does,
/// mirroring `_chroma_filter`'s `{similarity:.4g}:{blend:.4g}` for all inputs
/// (e.g. `0.18` → "0.18", `0.1` → "0.1", `0.123456` → "0.1235").
fn fmt_chroma(v: f64) -> String {
    fmt_g(v, 4)
}

/// A filtergraph accumulator that chains labeled nodes.
#[derive(Debug, Default)]
pub struct FilterGraph {
    nodes: Vec<String>,
}

impl FilterGraph {
    pub fn new() -> Self {
        FilterGraph::default()
    }

    /// Scale + crop an input to fill WxH (cover, never letterbox) → `out` label.
    pub fn scale_crop_fill(mut self, input: &str, w: u32, h: u32, out: &str) -> Self {
        self.nodes.push(format!(
            "[{input}]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}[{out}]"
        ));
        self
    }

    /// Overlay `top` on `base` at (x,y) → `out` label.
    pub fn overlay(mut self, base: &str, top: &str, x: i32, y: i32, out: &str) -> Self {
        self.nodes
            .push(format!("[{base}][{top}]overlay={x}:{y}[{out}]"));
        self
    }

    /// Chroma-key `input` (e.g. a greenscreen avatar) → `out`, mirroring the
    /// API's `chromakey={color}:{similarity}:{blend}` node. `color` is a hex
    /// string like `"0x00FF00"`; `similarity`/`blend` default around 0.18/0.10.
    pub fn chromakey(
        mut self,
        input: &str,
        color: &str,
        similarity: f64,
        blend: f64,
        out: &str,
    ) -> Self {
        self.nodes.push(format!(
            "[{input}]chromakey={color}:{}:{}[{out}]",
            fmt_chroma(similarity),
            fmt_chroma(blend)
        ));
        self
    }

    /// Burn `.ass` captions from `ass_path` (with `fonts_dir`) onto `input` →
    /// `out`, mirroring the API's `ass={path}:fontsdir={dir}` node. Both paths are
    /// escaped for the filtergraph parser via [`escape_ass_path`].
    pub fn ass(mut self, input: &str, ass_path: &str, fonts_dir: &str, out: &str) -> Self {
        self.nodes.push(format!(
            "[{input}]ass={}:fontsdir={}[{out}]",
            escape_ass_path(ass_path),
            escape_ass_path(fonts_dir)
        ));
        self
    }

    /// Vertically stack `top` over `bottom` → `out` (the split-screen / movie-over-
    /// gameplay format). Mirrors the API's `[top][bot]vstack=inputs=2[comp]`.
    pub fn vstack(mut self, top: &str, bottom: &str, out: &str) -> Self {
        self.nodes
            .push(format!("[{top}][{bottom}]vstack=inputs=2[{out}]"));
        self
    }

    /// Horizontally stack `left` beside `right` → `out` (side-by-side reaction).
    pub fn hstack(mut self, left: &str, right: &str, out: &str) -> Self {
        self.nodes
            .push(format!("[{left}][{right}]hstack=inputs=2[{out}]"));
        self
    }

    /// A raw node (escape hatch for effects the typed builders don't cover).
    pub fn raw(mut self, node: &str) -> Self {
        self.nodes.push(node.to_string());
        self
    }

    /// Render the `-filter_complex` value (nodes joined by `;`).
    pub fn build(&self) -> String {
        self.nodes.join(";")
    }

    pub fn node_count(&self) -> usize {
        self.nodes.len()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn builds_scale_crop_node() {
        let g = FilterGraph::new().scale_crop_fill("0:v", 1080, 1920, "bg");
        let s = g.build();
        assert!(s.contains("scale=1080:1920:force_original_aspect_ratio=increase"));
        assert!(s.contains("crop=1080:1920[bg]"));
    }

    #[test]
    fn chains_scale_then_overlay() {
        let g = FilterGraph::new()
            .scale_crop_fill("0:v", 1080, 1920, "bg")
            .overlay("bg", "1:v", 40, 1500, "comp");
        let s = g.build();
        assert_eq!(g.node_count(), 2);
        assert!(s.contains(";")); // two nodes joined
        assert!(s.ends_with("overlay=40:1500[comp]"));
    }

    #[test]
    fn raw_escape_hatch() {
        let s = FilterGraph::new().raw("[comp]gblur=sigma=3[out]").build();
        assert_eq!(s, "[comp]gblur=sigma=3[out]");
    }

    #[test]
    fn chromakey_matches_api_syntax() {
        let s = FilterGraph::new()
            .chromakey("1:v", "0x00FF00", 0.18, 0.10, "keyed")
            .build();
        // Mirrors compose_ffmpeg `chromakey={color}:{similarity}:{blend}`.
        assert_eq!(s, "[1:v]chromakey=0x00FF00:0.18:0.1[keyed]");
    }

    #[test]
    fn greenscreen_react_composites() {
        // The greenscreen react: key the reactor, then overlay onto gameplay.
        let g = FilterGraph::new()
            .scale_crop_fill("0:v", 1080, 1920, "bg")
            .chromakey("1:v", "0x00FF00", 0.18, 0.1, "fg")
            .overlay("bg", "fg", 0, 0, "comp");
        assert_eq!(g.node_count(), 3);
        assert!(g
            .build()
            .contains("chromakey=0x00FF00:0.18:0.1[fg];[bg][fg]overlay=0:0[comp]"));
    }

    #[test]
    fn vstack_builds_split_screen() {
        let s = FilterGraph::new().vstack("top", "bot", "comp").build();
        assert_eq!(s, "[top][bot]vstack=inputs=2[comp]");
    }

    #[test]
    fn hstack_builds_side_by_side() {
        let s = FilterGraph::new().hstack("left", "right", "comp").build();
        assert_eq!(s, "[left][right]hstack=inputs=2[comp]");
    }

    #[test]
    fn ass_burn_escapes_paths() {
        let s = FilterGraph::new()
            .ass("comp", "/tmp/a b/cap.ass", "/fonts", "final")
            .build();
        // The ':' in a Windows-style path and structural chars are escaped; here
        // the forward-slash POSIX path has no metas except none, so it passes through.
        assert_eq!(s, "[comp]ass=/tmp/a b/cap.ass:fontsdir=/fonts[final]");
    }

    #[test]
    fn escape_ass_path_escapes_metas_and_normalizes_backslashes() {
        // Windows drive path: backslashes -> forward slashes, then ':' escaped.
        assert_eq!(escape_ass_path(r"C:\subs\cap.ass"), r"C\:/subs/cap.ass");
        // Structural chars each get a backslash prefix.
        assert_eq!(escape_ass_path("a[b];c,d'e"), r"a\[b\]\;c\,d\'e");
    }
}
