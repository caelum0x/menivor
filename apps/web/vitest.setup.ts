import "@testing-library/jest-dom/vitest";
import { beforeEach } from "vitest";

// The shared transport falls back to a device key this browser already holds
// when a call carries no token (legacy guests; new ones are never minted on
// the web). Seed one so unit tests exercise an authenticated transport.
beforeEach(() => {
  window.localStorage.setItem("menivor.device.api_key", "test-device-key");
});
