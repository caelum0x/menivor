//! Hardware/codec capability + encoder selection for the local render farm
//! (`rf-render`/`rf-encode`). The actual probe (querying ffmpeg/OS for available
//! hwaccel encoders) is the injectable boundary; this crate owns the *selection
//! policy* — pick the fastest available hardware H.264/HEVC encoder for the host,
//! falling back to libx264 — so it is pure + unit-testable.

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Platform {
    MacOs,   // VideoToolbox
    Windows, // NVENC / QSV / AMF
    Linux,   // NVENC / VAAPI
}

#[derive(Debug, Clone, Default)]
pub struct Capabilities {
    pub videotoolbox: bool,
    pub nvenc: bool,
    pub qsv: bool,
    pub vaapi: bool,
    pub amf: bool,
}

/// An ffmpeg encoder name (video codec).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Encoder {
    VideotoolboxH264,
    NvencH264,
    QsvH264,
    VaapiH264,
    AmfH264,
    Libx264, // universal software fallback
}

impl Encoder {
    pub fn ffmpeg_name(self) -> &'static str {
        match self {
            Encoder::VideotoolboxH264 => "h264_videotoolbox",
            Encoder::NvencH264 => "h264_nvenc",
            Encoder::QsvH264 => "h264_qsv",
            Encoder::VaapiH264 => "h264_vaapi",
            Encoder::AmfH264 => "h264_amf",
            Encoder::Libx264 => "libx264",
        }
    }

    pub fn is_hardware(self) -> bool {
        !matches!(self, Encoder::Libx264)
    }
}

/// Select the best available H.264 encoder for the host, preferring hardware in a
/// platform-idiomatic order and always falling back to libx264.
pub fn select_encoder(platform: Platform, caps: &Capabilities) -> Encoder {
    match platform {
        Platform::MacOs => {
            if caps.videotoolbox {
                Encoder::VideotoolboxH264
            } else {
                Encoder::Libx264
            }
        }
        Platform::Windows => {
            if caps.nvenc {
                Encoder::NvencH264
            } else if caps.qsv {
                Encoder::QsvH264
            } else if caps.amf {
                Encoder::AmfH264
            } else {
                Encoder::Libx264
            }
        }
        Platform::Linux => {
            if caps.nvenc {
                Encoder::NvencH264
            } else if caps.vaapi {
                Encoder::VaapiH264
            } else {
                Encoder::Libx264
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn macos_prefers_videotoolbox() {
        let caps = Capabilities {
            videotoolbox: true,
            ..Default::default()
        };
        assert_eq!(
            select_encoder(Platform::MacOs, &caps),
            Encoder::VideotoolboxH264
        );
        assert_eq!(
            select_encoder(Platform::MacOs, &Capabilities::default()),
            Encoder::Libx264
        );
    }

    #[test]
    fn windows_prefers_nvenc_then_qsv_then_amf() {
        let nv = Capabilities {
            nvenc: true,
            qsv: true,
            amf: true,
            ..Default::default()
        };
        assert_eq!(select_encoder(Platform::Windows, &nv), Encoder::NvencH264);
        let qsv = Capabilities {
            qsv: true,
            amf: true,
            ..Default::default()
        };
        assert_eq!(select_encoder(Platform::Windows, &qsv), Encoder::QsvH264);
        let amf = Capabilities {
            amf: true,
            ..Default::default()
        };
        assert_eq!(select_encoder(Platform::Windows, &amf), Encoder::AmfH264);
    }

    #[test]
    fn linux_prefers_nvenc_then_vaapi() {
        let vaapi = Capabilities {
            vaapi: true,
            ..Default::default()
        };
        assert_eq!(select_encoder(Platform::Linux, &vaapi), Encoder::VaapiH264);
    }

    #[test]
    fn always_falls_back_to_libx264() {
        let e = select_encoder(Platform::Linux, &Capabilities::default());
        assert_eq!(e, Encoder::Libx264);
        assert!(!e.is_hardware());
        assert_eq!(e.ffmpeg_name(), "libx264");
    }
}
