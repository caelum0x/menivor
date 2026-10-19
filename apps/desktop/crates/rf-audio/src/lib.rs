//! Audio filter chain (`rf-audio`) — the audio counterpart to `rf-compose`.
//! Builds the FFmpeg audio filtergraph for a reel (narration + optional BGM +
//! optional ducking), **byte-identical** to the cloud's `render-core` audio
//! branch, so a desktop-rendered reel's audio matches the cloud's.
//!
//! Pure string assembly; input indices are injected, no I/O.

/// The BGM-ducking node (BGM compressed under the narration side-chain) — the
/// exact string `render-core` emits.
pub const DUCK: &str = "sidechaincompress=threshold=0.03:ratio=8:attack=5:release=250";

/// Which inputs feed the audio mix and whether to duck the BGM.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct AudioSpec {
    /// FFmpeg input index carrying the narration stream.
    pub narration_input: u32,
    /// FFmpeg input index carrying the BGM, if any.
    pub bgm_input: Option<u32>,
    /// Duck the BGM under the narration (only applies when BGM is present).
    pub duck: bool,
}

/// The assembled audio chain: the filter nodes + the label to `-map`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AudioChain {
    /// The `;`-joined audio filter nodes (empty when narration-only).
    pub filtergraph: String,
    /// The audio pad to `-map`: `[aout]` when mixed, else the raw narration pad.
    pub output_label: String,
    /// Whether any filter node was emitted (false = map narration directly).
    pub has_filter: bool,
}

/// Build the audio chain, mirroring `render-core`'s branch exactly:
/// - BGM + duck → side-chain-compress the BGM under narration, then `amix`;
/// - BGM only → `amix` narration + BGM;
/// - narration only → no filter; map the narration pad directly.
pub fn build_audio(spec: &AudioSpec) -> AudioChain {
    let nar = spec.narration_input;
    match (spec.bgm_input, spec.duck) {
        (Some(bgm), true) => AudioChain {
            filtergraph: format!(
                "[{bgm}:a][{nar}:a]{DUCK}[bgmduck];[{nar}:a][bgmduck]amix=inputs=2:duration=first[aout]"
            ),
            output_label: "[aout]".to_string(),
            has_filter: true,
        },
        (Some(bgm), false) => AudioChain {
            filtergraph: format!("[{nar}:a][{bgm}:a]amix=inputs=2:duration=first[aout]"),
            output_label: "[aout]".to_string(),
            has_filter: true,
        },
        (None, _) => AudioChain {
            filtergraph: String::new(),
            output_label: format!("[{nar}:a]"),
            has_filter: false,
        },
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bgm_with_duck_matches_render_core() {
        let chain = build_audio(&AudioSpec {
            narration_input: 2,
            bgm_input: Some(3),
            duck: true,
        });
        assert_eq!(
            chain.filtergraph,
            "[3:a][2:a]sidechaincompress=threshold=0.03:ratio=8:attack=5:release=250[bgmduck];\
[2:a][bgmduck]amix=inputs=2:duration=first[aout]"
        );
        assert_eq!(chain.output_label, "[aout]");
        assert!(chain.has_filter);
    }

    #[test]
    fn bgm_without_duck_matches_render_core() {
        let chain = build_audio(&AudioSpec {
            narration_input: 2,
            bgm_input: Some(3),
            duck: false,
        });
        assert_eq!(
            chain.filtergraph,
            "[2:a][3:a]amix=inputs=2:duration=first[aout]"
        );
        assert_eq!(chain.output_label, "[aout]");
    }

    #[test]
    fn narration_only_has_no_filter() {
        let chain = build_audio(&AudioSpec {
            narration_input: 1,
            bgm_input: None,
            duck: true, // ignored without BGM, exactly like render-core
        });
        assert!(chain.filtergraph.is_empty());
        assert_eq!(chain.output_label, "[1:a]");
        assert!(!chain.has_filter);
    }

    #[test]
    fn duck_flag_is_ignored_without_bgm() {
        let with = build_audio(&AudioSpec {
            narration_input: 0,
            bgm_input: None,
            duck: true,
        });
        let without = build_audio(&AudioSpec {
            narration_input: 0,
            bgm_input: None,
            duck: false,
        });
        assert_eq!(with, without);
    }
}
