/**
 * Auth domain — device session creation + file uploads.
 * Thin re-export from lib/api.ts organized by domain.
 */

export {
  createDeviceSession,
  type DeviceSession,
  presign,
  presignAndUpload,
  registerPushToken,
  type PushTokenRegistration,
  registerUpload,
} from "@/lib/api";
