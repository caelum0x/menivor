/**
 * Apple App Site Association for the Menivor iOS app (bundle
 * com.arhansuba.menivor, team 947G2G2JXJ). The app declares
 * `applinks:menivor.com` and handles /r/{token} share links and
 * /invite/{token} team invites; without this file iOS opens those links in
 * Safari instead of the app. Served as JSON at the extensionless path Apple
 * fetches (https://menivor.com/.well-known/apple-app-site-association).
 */
export const dynamic = "force-static";

const APP_ID = "947G2G2JXJ.com.arhansuba.menivor";

export function GET(): Response {
  const body = {
    applinks: {
      details: [
        {
          appIDs: [APP_ID],
          components: [
            { "/": "/r/*", comment: "Public reel share links" },
            { "/": "/invite/*", comment: "Team invites" },
          ],
        },
      ],
    },
  };
  return new Response(JSON.stringify(body), {
    headers: {
      "content-type": "application/json",
      "cache-control": "public, max-age=3600",
    },
  });
}
