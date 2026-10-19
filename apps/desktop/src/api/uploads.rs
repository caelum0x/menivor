//! Presign and streaming file-upload orchestration.

use std::fs::File;
use std::path::Path;

use super::errors::{connection_failure, status_failure};
use super::models::{
    PresignData, PresignInput, RegisterUploadInput, RegisteredUpload, UploadedObject,
};
use super::{ApiClient, ApiFailure, ApiFailureKind};

impl ApiClient {
    pub(crate) fn upload_file(
        &self,
        path: &Path,
        content_type: &str,
    ) -> Result<UploadedObject, ApiFailure> {
        let metadata = path.metadata().map_err(|error| ApiFailure {
            kind: ApiFailureKind::Request,
            status: None,
            message: format!("Could not read the selected file: {error}"),
        })?;
        if !metadata.is_file() {
            return Err(ApiFailure {
                kind: ApiFailureKind::Request,
                status: None,
                message: "The selected upload is not a file.".into(),
            });
        }
        let filename = path
            .file_name()
            .and_then(|name| name.to_str())
            .filter(|name| !name.is_empty())
            .ok_or_else(|| ApiFailure {
                kind: ApiFailureKind::Request,
                status: None,
                message: "The selected file has no usable filename.".into(),
            })?;
        let presigned: PresignData = self.post(
            "/uploads/presign",
            &PresignInput {
                filename,
                content_type,
                size: metadata.len(),
            },
        )?;
        let mut request = self.agent.put(&presigned.upload_url);
        if presigned.headers.is_empty() {
            request = request.header("Content-Type", content_type);
        } else {
            for (name, value) in &presigned.headers {
                request = request.header(name, value);
            }
        }
        let file = File::open(path).map_err(|error| ApiFailure {
            kind: ApiFailureKind::Request,
            status: None,
            message: format!("Could not open the selected file: {error}"),
        })?;
        let response = request.send(file).map_err(connection_failure)?;
        let status = response.status().as_u16();
        if !(200..300).contains(&status) {
            return Err(status_failure(status, "Storage rejected the file upload."));
        }
        let kind = if content_type.starts_with("image/") {
            "image"
        } else if content_type.starts_with("video/") {
            "video"
        } else if content_type.starts_with("audio/") {
            "audio"
        } else {
            "upload"
        };
        let registered: RegisteredUpload = self.post(
            "/uploads/register",
            &RegisterUploadInput {
                key: &presigned.key,
                kind,
            },
        )?;
        Ok(UploadedObject {
            key: registered.key,
            get_url: presigned.get_url,
        })
    }
}
