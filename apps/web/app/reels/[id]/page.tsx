import { JobDetailsPage } from "@/src/features/jobs-library";

/**
 * Reel detail — the live render view with every post-generation action
 * (retry, dub, schedule/publish, cover, b-roll, social). Reuses the shared
 * jobs-library detail feature so the Reels library and the classic Jobs view
 * stay in lockstep. The route param `id` is the reel's job id.
 */
export default JobDetailsPage;
