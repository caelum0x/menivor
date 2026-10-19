/**
 * Connections domain — social platform OAuth connections and publishing.
 * (GET /connections, POST /connections/authorize, /connections/complete,
 *  POST /connections/disconnect, POST /jobs/{id}/publish)
 */

export {
  completeConnect,
  disconnect,
  getConnections,
  getPilotCapabilities,
  publishJobTo,
  startConnect,
} from "@/lib/api";
