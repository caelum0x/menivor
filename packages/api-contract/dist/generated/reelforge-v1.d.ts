export interface ActorBody {
    attest_synthetic?: boolean;
    look_prompt: string;
    name: string;
    persona?: string;
    product_shot_template?: string;
    voice_design_prompt: string;
}
export interface AdCreate {
    click_url?: string;
    ends_at?: string | null;
    name: string;
    sponsor?: string;
    starts_at?: string | null;
    title_id: string;
}
export interface AddKeywordBody {
    app_id: string;
    app_name?: string;
    country?: string;
    term: string;
}
/**
 * Store a customer's own provider API key (the secret is write-only).
 */
export interface AddProviderKeyRequest {
    label?: string;
    priority?: number;
    provider_key: string;
    secret: string;
}
export interface AddTitles {
    job_ids: Array<string>;
}
/**
 * ``GET /api/v1/admin/erasure-requests`` — cross-tenant erasure requests.
 *
 * Platform-admin (``is_staff``) ONLY — HTTP 403 for a non-staff caller. ``data``
 * is a list of :class:`ErasureRequestModel` across every tenant, newest first.
 */
export interface AdminErasureRequestsResponse {
    data?: Array<ErasureRequestModel>;
    message?: string | null;
    status?: number;
}
/**
 * Envelope for ``GET /api/v1/admin/jobs``; ``data`` is a list of
 * :class:`AdminJobModel`. Platform-admin (``is_staff``) only.
 */
export interface AdminJobsResponse {
    data?: Array<{
        [key: string]: unknown;
    }>;
    message?: string | null;
    status?: number;
}
/**
 * ``GET /api/v1/admin/retention`` — cross-tenant retention-policy overview.
 *
 * Platform-admin (``is_staff``) ONLY. ``data`` is a list of every configured
 * :class:`RetentionPolicyModel` so an operator can audit retention posture.
 */
export interface AdminRetentionResponse {
    data?: Array<RetentionPolicyModel>;
    message?: string | null;
    status?: number;
}
/**
 * Envelope for ``GET /api/v1/admin/users``; ``data`` is a list of
 * :class:`AdminUserModel`. Platform-admin (``is_staff``) only — HTTP 403 for a
 * non-staff caller, HTTP 401 when unauthenticated.
 */
export interface AdminUsersResponse {
    data?: Array<{
        [key: string]: unknown;
    }>;
    message?: string | null;
    status?: number;
}
/**
 * Envelope for ``GET /api/v1/admin/workspaces``; ``data`` is a list of
 * :class:`AdminWorkspaceModel`. Platform-admin (``is_staff``) only.
 */
export interface AdminWorkspacesResponse {
    data?: Array<{
        [key: string]: unknown;
    }>;
    message?: string | null;
    status?: number;
}
export interface AdsBody {
    aspects?: Array<string>;
    avatar_id?: string;
    caption_style?: string;
    language?: "en" | "tr" | "auto";
    mode?: "captions" | "voiceover" | "avatar";
    platforms?: Array<string>;
    script: string;
    voice_id?: string;
    voice_name?: string;
}
export interface AiImageBody {
    model?: string;
    prompt: string;
}
export interface AiRequest {
    kinds: Array<string>;
    languages?: Array<string>;
    source_language?: string;
}
/**
 * A single creator's BI analytics dashboard (strictly caller-scoped).
 *
 * Mirrors the output of :func:`app.services.analytics.creator_analytics`
 * (funnel, cost-over-time, credit burn + live balance, render-time
 * percentiles, usage breakdowns and totals) merged with the caller's most-used
 * templates/hooks under ``top_content``. ``ConfigDict(extra="allow")`` keeps
 * the payload forward-compatible — the service may attach new nested metrics
 * without a schema change breaking serialisation.
 */
export interface AnalyticsData {
    by_language?: {
        [key: string]: number;
    };
    by_layout?: {
        [key: string]: number;
    };
    by_variants?: {
        [key: string]: number;
    };
    cost_by_day?: Array<{
        [key: string]: unknown;
    }>;
    credits?: {
        [key: string]: unknown;
    };
    days?: number;
    funnel?: {
        [key: string]: number;
    };
    render_time?: {
        [key: string]: unknown;
    };
    top_content?: {
        [key: string]: Array<{
            [key: string]: unknown;
        }>;
    };
    totals?: {
        [key: string]: unknown;
    };
    user_id: string;
    [key: string]: unknown;
}
/**
 * ``GET /api/v1/me/analytics`` — the caller's BI analytics dashboard.
 */
export interface AnalyticsResponse {
    data: AnalyticsData;
    message?: string | null;
    status?: number;
}
export interface AnalyzeBody {
    angle_count?: number;
    language?: string | null;
    product?: ManualProduct | null;
    url?: string | null;
    use_llm?: boolean;
}
export interface AngleIn {
    cta?: string;
    hook?: string;
    kind?: string;
    offer?: string;
    pain?: string;
    proof?: string;
    source?: string;
}
/**
 * ``POST /api/v1/me/api-keys`` body — mint a personal programmatic API key.
 *
 * Only a human-friendly ``name`` (label) is accepted so the caller can tell
 * their keys apart (e.g. "CI", "n8n", "laptop"). The name is required and
 * trimmed/length-capped by the controller; the raw secret is generated
 * server-side (never client-supplied) so a caller can never inject a weak key.
 */
export interface ApiKeyCreateRequest {
    name: string;
}
export interface ApiKeyCreatedData {
    created_at?: string | null;
    id: string;
    key: string;
    name: string;
    prefix: string;
}
/**
 * ``POST /api/v1/me/api-keys`` — the ONE-TIME reveal of a freshly minted key.
 *
 * SECURITY: ``key`` is the FULL raw secret and is returned **exactly once**, at
 * creation. The server stores only its SHA-256 digest, so the raw value is
 * **unrecoverable** afterwards — a lost key must be revoked and re-created. The
 * non-secret ``prefix`` is safe to persist/display so the caller can recognise
 * the key later (subsequent list calls never return ``key``).
 */
export interface ApiKeyCreatedResponse {
    data: ApiKeyCreatedData;
    message?: string | null;
    status?: number;
}
/**
 * One API key serialised to its public, caller-scoped envelope.
 *
 * NEVER carries the raw key or the full hash — only the id, label, non-secret
 * ``prefix``, usage/lifecycle metadata, and timestamps are exposed.
 *
 * POWER-USER TIER: also surfaces the key's per-minute ``rate_limit_per_min``
 * (``null`` = inherit the plan/config default), its ``monthly_quota``
 * (``null`` = unlimited), and ``usage_this_month`` — the request count already
 * consumed by this key in the current calendar month (0 when unused).
 */
export interface ApiKeyData {
    created_at?: string | null;
    id: string;
    last_used_at?: string | null;
    monthly_quota?: number | null;
    name: string;
    prefix: string;
    rate_limit_per_min?: number | null;
    revoked?: boolean;
    usage_this_month?: number;
}
/**
 * ``GET /api/v1/me/api-keys`` — the caller's keys (newest first).
 *
 * ``data`` is the list of the caller's keys (active *and* revoked, for a full
 * audit view). The raw key and full hash are **never** included — only the
 * non-secret ``prefix`` and lifecycle metadata.
 */
export interface ApiKeyListResponse {
    data?: Array<ApiKeyData>;
    message?: string | null;
    status?: number;
}
/**
 * One API key's current-month usage + limits (POWER-USER TIER quotas).
 *
 * Caller-scoped. Never carries the raw key or hash — only the id, label,
 * non-secret ``prefix``, the ``period_ym`` (``'YYYY-MM'``) the counts apply to,
 * the requests ``used`` so far this month, and the key's limits. ``remaining``
 * is ``monthly_quota - used`` (floored at 0) or ``null`` when the key has no
 * monthly cap (unlimited).
 */
export interface ApiKeyUsageModel {
    id: string;
    monthly_quota?: number | null;
    name: string;
    period_ym: string;
    prefix: string;
    rate_limit_per_min?: number | null;
    remaining?: number | null;
    used?: number;
}
/**
 * ``GET /api/v1/me/api-keys/usage`` — current-month usage for the caller's keys.
 *
 * ``data`` defaults to ``[]`` because the shared ``utils.get_response`` envelope
 * drops a falsy payload — a caller with no keys must still validate.
 */
export interface ApiKeyUsageResponse {
    data?: Array<ApiKeyUsageModel>;
    message?: string | null;
    status?: number;
}
export interface AppStoreConnectBody {
    issuer_id: string;
    key_id: string;
    private_key_pem: string;
}
export interface ApproveBody {
    text?: string;
}
export interface ApproveRequest {
    engine?: string | null;
    plan: {
        [key: string]: unknown;
    };
    quoted_credits: number;
}
export interface ApproversBody {
    slack_user_ids?: Array<string>;
}
export interface AskBody {
    ad_account_id?: string | null;
    days?: number;
    question: string;
}
export interface AttachJobBody {
    job_id: string;
}
export interface AttributionRequest {
    referrer?: string;
    utm_campaign?: string;
    utm_medium?: string;
    utm_source?: string;
}
export interface AudienceBody {
    age_max?: number;
    age_min?: number;
    countries?: Array<string>;
    gender?: string;
}
export interface AudioBody {
    instrumental?: boolean;
    model: string;
    prompt: string;
}
export interface AudioRequest {
    bgm_file?: string | null;
    bgm_type?: string | null;
    bgm_volume?: number | null;
    video_language?: string | null;
    video_script: string;
    video_source?: string | null;
    voice_name?: string | null;
    voice_rate?: number | null;
    voice_volume?: number | null;
}
export interface AuditBody {
    url: string;
}
/**
 * Envelope for a workspace's audit trail; ``data`` is a list of
 * :class:`AuditEntryModel` descriptors, newest first.
 *
 * Gated on ``audit.read`` in the target workspace and strictly tenant-scoped, so
 * a member of one tenant can never read another tenant's trail. Defaults to
 * ``[]`` so an empty trail still validates against the falsy-dropping envelope.
 */
export interface AuditResponse {
    data?: Array<{
        [key: string]: unknown;
    }>;
    message?: string | null;
    status?: number;
}
/**
 * The opaque authorize URL + single-use CSRF state for an OAuth connect.
 */
export interface AuthorizeData {
    authorize_url: string;
    provider: string;
    state: string;
}
/**
 * ``GET /api/v1/connections/{provider}/authorize`` — where to send the browser.
 *
 * ``state`` is an opaque, single-use CSRF token the caller must echo back on the
 * callback; ``authorize_url`` already embeds it. Nothing sensitive is returned.
 */
export interface AuthorizeResponse {
    data: AuthorizeData;
    message?: string | null;
    status?: number;
}
/**
 * List of avatars (merged presets + provider catalog); ``data`` is a list.
 */
export interface AvatarListResponse {
    data: Array<{
        [key: string]: unknown;
    }>;
    message?: string | null;
    status?: number;
}
export interface Ban {
    viewer_id: string;
}
export interface BaseResponse {
    data?: unknown;
    message?: string | null;
    status?: number;
}
/**
 * Envelope for ``GET /api/v1/batches/{batch_id}`` — the batch's variants.
 *
 * ``jobs`` lists every variant of the batch owned by the caller (oldest first,
 * so ``job_id`` — the first created variant — leads), enabling a side-by-side
 * review of the N reels a single ``variants`` request fanned out.
 */
export interface BatchData {
    batch_id: string;
    jobs?: Array<BatchJobData>;
    [key: string]: unknown;
}
/**
 * One variant's status inside a batch-review listing (Phase-10).
 *
 * Only the fields a batch-review UI needs: the job id, its live
 * ``state``/``progress``, and — when the render has finished — a presigned
 * ``result_url`` plus the ``poster_key`` of its thumbnail frame. Both are
 * optional (a still-processing variant has neither). ``extra="allow"`` mirrors
 * the ``JobData`` convention so forward-compatible fields can be attached
 * without a schema break.
 */
export interface BatchJobData {
    cover_key?: string | null;
    cover_url?: string | null;
    job_id: string;
    poster_key?: string | null;
    poster_url?: string | null;
    preview_key?: string | null;
    preview_url?: string | null;
    progress?: number;
    result_url?: string | null;
    state: number;
    [key: string]: unknown;
}
/**
 * ``GET /api/v1/batches/{batch_id}`` — a batch of variant jobs for review.
 */
export interface BatchResponse {
    data: BatchData;
    message?: string | null;
    status?: number;
}
export interface Beacons {
    device_id?: string;
    events: Array<{
        [key: string]: unknown;
    }>;
}
export interface Beat {
    camera_move?: "static" | "push_in" | "pull_out" | "pan" | "handheld" | "unknown";
    end_s: number;
    framing?: "close" | "medium" | "wide" | "unknown";
    index: number;
    line?: string;
    on_screen_text?: string;
    role?: string;
    shot_type?: "talking" | "reaction" | "insert" | "establishing" | "product_card" | "text_card";
    speaker?: "narrator" | "on_camera" | "none";
    start_s: number;
}
export interface BeatFitBody {
    beats?: Array<number>;
    cuts?: Array<number>;
    fps?: number;
}
export interface BeatIn {
    dialogue?: string;
    scene_id: string;
    summary: string;
    weight?: number;
}
export interface BetaApproveBody {
    approved?: boolean;
    email: string;
}
export interface BetaRequestBody {
    email: string;
    source?: string;
    use_case?: string;
}
export interface BgmRetrieveResponse {
    data?: unknown;
    message?: string | null;
    status?: number;
}
export interface BgmUploadResponse {
    data?: unknown;
    message?: string | null;
    status?: number;
}
export interface BlueskyBody {
    app_password: string;
    handle: string;
    pds?: string;
}
export interface Body_check_content_credentials_api_v1_legal_content_credentials_post {
    file: string;
}
export interface Body_upload_bgm_file_api_v1_musics_post {
    file: string;
}
export interface Body_upload_video_material_file_api_v1_video_materials_post {
    file: string;
}
/**
 * The caller's brand watermark settings serialised to the public envelope.
 *
 * Mirrors the :class:`~app.models.db.models.UserBrand` column defaults so a
 * creator who has never configured a brand still receives a sensible, applied
 * watermark shape. ``logo_url`` is a short-lived presigned GET URL for the
 * stored logo, present only when a ``logo_key`` is set (``None`` otherwise).
 */
export interface BrandData {
    enabled?: boolean;
    logo_key?: string;
    logo_url?: string | null;
    opacity?: number;
    position?: string;
    updated_at?: string | null;
    [key: string]: unknown;
}
export interface BrandImportBody {
    name?: string | null;
    preset_id?: string | null;
    save?: boolean;
    source: "website" | "rally";
    value: string;
}
/**
 * Request body for ``PUT /api/v1/me/brand`` (partial update).
 *
 * Every field is optional so a caller may update just one setting; an omitted
 * (``None``) field leaves the persisted value untouched. Values are validated
 * at the controller boundary: ``position`` must be one of the four known
 * corners and ``opacity`` must fall in ``[0.0, 1.0]`` (both ``400`` otherwise),
 * and a supplied ``logo_key`` must reference an upload the caller owns
 * (``403`` otherwise). Passing ``logo_key=""`` clears the watermark logo.
 */
export interface BrandRequest {
    enabled?: boolean | null;
    logo_key?: string | null;
    opacity?: number | null;
    position?: string | null;
}
/**
 * ``GET``/``PUT`` ``/api/v1/me/brand`` — the caller's brand watermark.
 */
export interface BrandResponse {
    data: BrandData;
    message?: string | null;
    status?: number;
}
export interface BrandSpacesBody {
    brand_space_ids?: Array<string>;
}
export interface BriefRequest {
    language?: string;
    url: string;
}
/**
 * One suggested B-roll cutaway clip.
 *
 * ``broll_key`` is the R2 object key of the fetched clip, always written under
 * the requesting job's own ``jobs/<job_id>/broll/`` prefix (owned by that job).
 * ``duration`` may be ``0.0`` when it could not be probed.
 */
export interface BrollClip {
    broll_key: string;
    duration?: number;
    source?: string;
    term?: string;
    [key: string]: unknown;
}
/**
 * Request body for canonical ``POST /api/v1/generation/broll/generate``.
 *
 * Unlike the job-scoped ``suggest`` route (which derives prompts server-side),
 * the studio accepts a **free-text** ``prompt`` — it *is* the product primitive.
 * The prompt is length-capped and moderated server-side before any GPU spend.
 *
 * * ``prompt`` (required) — the motion description (1..500 chars).
 * * ``mode`` — ``"t2v"`` (default) or ``"i2v"``; ``i2v`` requires ``image_key``.
 * * ``image_key`` — an R2 key the caller OWNS (validated server-side, never an
 *   arbitrary URL) used as the i2v reference frame.
 * * ``aspect`` — output aspect (defaults to portrait 1080x1920).
 * * ``workflow_id`` — optional comfyui-deploy deployment / motion preset id.
 * * ``seed`` — optional determinism seed.
 */
export interface BrollGenerateRequest {
    aspect?: VideoAspect | null;
    image_key?: string | null;
    mode?: string | null;
    prompt: string;
    seed?: number | null;
    workflow_id?: string | null;
}
/**
 * One studio generation's lifecycle snapshot (a ``Job(kind='broll_gen')``).
 *
 * ``generation_id`` is the underlying job id — pollable via
 * ``GET /api/v1/generation/broll/generations/{id}``. ``state`` follows the shared job
 * states (4 processing, 1 complete, -1 failed); ``broll_key`` is the rendered
 * clip's R2 key once complete (empty until then).
 */
export interface BrollGeneration {
    broll_key?: string;
    correlation_id?: string;
    duration?: number;
    error?: string;
    generation_id: string;
    progress?: number;
    result_url?: string;
    retry_eligible?: boolean;
    state?: number;
    [key: string]: unknown;
}
/**
 * Canonical B-roll create/poll response envelope.
 */
export interface BrollGenerationResponse {
    data: BrollGeneration;
    message?: string | null;
    status?: number;
}
/**
 * Canonical B-roll history response for the authenticated caller.
 */
export interface BrollGenerationsResponse {
    data?: Array<BrollGeneration>;
    message?: string | null;
    status?: number;
}
/**
 * One curated (or user) AI B-roll motion preset for the studio picker.
 *
 * ``prompt_template`` is a starter prompt the UI drops into the prompt box (a
 * ``{subject}`` placeholder, if present, is filled by the creator);
 * ``default_params`` carries motion knobs forwarded to generation; ``mode`` is
 * ``t2v`` or ``i2v``.
 */
export interface BrollPreset {
    default_params?: {
        [key: string]: unknown;
    };
    description?: string;
    id: string;
    mode?: string;
    name: string;
    prompt_template?: string;
    thumbnail_url?: string;
    workflow_id?: string;
    [key: string]: unknown;
}
/**
 * ``GET /broll/presets`` — the caller's available motion presets.
 */
export interface BrollPresetsResponse {
    data?: Array<BrollPreset>;
    message?: string | null;
    status?: number;
}
/**
 * Envelope for a B-roll suggestion response: the list of suggested clips.
 *
 * ``clips`` may be empty — B-roll is best-effort, so a provider/LLM failure
 * yields an empty list rather than an error.
 */
export interface BrollSuggestData {
    clips?: Array<BrollClip>;
    [key: string]: unknown;
}
/**
 * Request body for ``POST /api/v1/jobs/{job_id}/broll/suggest``.
 *
 * Both fields are optional so a bare ``{}`` body works: ``source`` selects the
 * backend — a stock provider (``pexels`` / ``pixabay`` / ...; the service
 * defaults it) or ``"ai"`` to generate motion clips via the ``broll_gen``
 * provider (ComfyUI/Wan) — and ``amount`` caps how many clips to fetch
 * (1..``_MAX_BROLL_AMOUNT``; the AI path is capped tighter for GPU cost). The
 * reel's search keywords / prompts are derived server-side from the *job's own*
 * subject/script, never from the client, so no free-text prompt is accepted here.
 */
export interface BrollSuggestRequest {
    amount?: number | null;
    source?: string | null;
}
/**
 * ``POST /api/v1/jobs/{job_id}/broll/suggest`` — suggested cutaway clips.
 */
export interface BrollSuggestResponse {
    data: BrollSuggestData;
    message?: string | null;
    status?: number;
}
/**
 * One calendar entry — the safe, render-only projection of a schedule.
 *
 * Mirrors :func:`app.services.calendar._safe_dto`: exactly these five fields,
 * never ``user_id`` / ``result`` / ``error`` / ``attempts`` /
 * ``youtube_privacy_status`` — no cross-tenant data, no private financials.
 */
export interface CalendarEntryModel {
    id: string;
    job_id?: string | null;
    platforms?: Array<string>;
    scheduled_at?: string | null;
    status?: string;
}
/**
 * ``GET /api/v1/me/calendar`` — the caller's window of schedules.
 *
 * ``data`` defaults to ``[]`` because the shared ``utils.get_response`` envelope
 * drops a falsy payload — an empty window must still validate.
 */
export interface CalendarResponse {
    data?: Array<CalendarEntryModel>;
    message?: string | null;
    status?: number;
}
export interface CanonCreateBody {
    brand_avoid?: Array<string>;
    brand_tone?: Array<string>;
    character_id?: string;
    language?: string;
    name: string;
    palette?: Array<string>;
    product_claims?: Array<string>;
    product_descriptors?: Array<string>;
    product_name?: string;
    style?: string;
    typography?: Array<string>;
    voice_id?: string;
    voice_tone?: string;
}
/**
 * Same value surface as create, minus the header ``name``/binding.
 */
export interface CanonLockBody {
    brand_avoid?: Array<string>;
    brand_tone?: Array<string>;
    language?: string;
    palette?: Array<string>;
    product_claims?: Array<string>;
    product_descriptors?: Array<string>;
    product_name?: string;
    style?: string;
    typography?: Array<string>;
    voice_id?: string;
    voice_tone?: string;
}
/**
 * Stable route roots clients use for generation workflows.
 */
export interface CanonicalGenerationRoutes {
    broll: string;
    reels: string;
}
export interface CaptionStyle {
    burned_in?: boolean;
    case?: "lower" | "sentence" | "upper" | "mixed" | "none";
    position?: "top" | "middle" | "bottom" | "none";
    present?: boolean;
    words_per_caption?: number;
}
/**
 * Caption-style catalog; ``data`` is a list of preset descriptors.
 *
 * ``data`` defaults to ``[]`` because the shared ``utils.get_response``
 * envelope drops a falsy payload — an empty catalog must still validate as an
 * empty list rather than a missing field.
 */
export interface CaptionStylesResponse {
    data?: Array<{
        [key: string]: unknown;
    }>;
    message?: string | null;
    status?: number;
}
/**
 * Where to continue after paying (a same-site path, default ``/create``).
 */
export interface CardCheckRequest {
    next?: string | null;
}
/**
 * ``POST /api/v1/me/workspaces/{id}/change-plan`` body — switch plan (DB-authoritative).
 */
export interface ChangePlanRequest {
    plan_key: string;
}
/**
 * Create a named channel: render matrix + source list + autorun switch.
 */
export interface ChannelCreateRequest {
    accounts?: Array<string>;
    aspects?: Array<string>;
    autorun?: boolean;
    hooks?: Array<string>;
    max_per_account?: number | null;
    max_words?: number | null;
    name: string;
    platforms?: Array<string>;
    source_items?: Array<SourceItemIn>;
    subject?: string;
    template_slug?: string;
    voice_id?: string | null;
}
export interface ChannelDraftBody {
    caption?: string;
    channel_id: string;
    hashtags?: Array<string>;
}
export interface ChannelPostsBody {
    drafts: Array<ChannelDraftBody>;
    job_id?: string;
    scheduled_at?: string | null;
    tone?: string;
}
export interface ChannelUpdate {
    brand_colors?: Array<string> | null;
    handle?: string | null;
    layout?: string | null;
    tagline?: string | null;
    title?: string | null;
}
/**
 * Partial update of a channel (omitted fields are left unchanged).
 */
export interface ChannelUpdateRequest {
    accounts?: Array<string> | null;
    aspects?: Array<string> | null;
    autorun?: boolean | null;
    hooks?: Array<string> | null;
    max_per_account?: number | null;
    max_words?: number | null;
    name?: string | null;
    platforms?: Array<string> | null;
    source_items?: Array<SourceItemIn> | null;
    subject?: string | null;
    template_slug?: string | null;
    voice_id?: string | null;
}
export interface ChapterBody {
    speed?: number;
    text: string;
    voice?: string;
}
export interface CharacterBody {
    descriptors?: Array<string>;
    lora_ref?: string;
    name: string;
    negative?: Array<string>;
    reference_images?: Array<string>;
    style?: string;
}
export interface CharacterIn {
    character_id: string;
    descriptors?: Array<string>;
    lora_ref?: string;
    name: string;
    negative?: Array<string>;
    reference_images?: Array<string>;
    style?: string;
}
export interface ChatPost {
    body: string;
}
export interface ChatRules {
    chat_enabled?: boolean | null;
    slow_mode_s?: number | null;
}
export interface Checkout {
    coupon_code?: string | null;
    offer_id: string;
}
/**
 * Hosted-checkout payload returned to the client.
 */
export interface CheckoutData {
    checkout_url: string;
    [key: string]: unknown;
}
export interface CheckoutResponse {
    data: CheckoutData;
    message?: string | null;
    status?: number;
}
export interface ChipBody {
    action_id?: string | null;
    choice: "yes" | "no" | "connect" | "retry" | "skip" | "approve" | "reject" | "use_product" | "recheck";
    edits?: {
        [key: string]: unknown;
    } | null;
    step?: string;
    value?: string | null;
}
/**
 * Create a long->short auto-clipping job.
 *
 * Exactly one source must be supplied: ``source_video_key`` (an owned R2 object
 * key) OR ``source_url`` (an external video URL).
 */
export interface ClipJobCreateRequest {
    captions?: "hormozi" | "ass_karaoke" | null;
    generation_profile_id?: string;
    language?: string;
    max_len_s?: number;
    min_len_s?: number;
    publish_targets?: Array<"tiktok" | "instagram" | "youtube" | "x" | "linkedin">;
    quote?: {
        [key: string]: unknown;
    } | null;
    score_floor?: number;
    source_url?: string;
    source_video_key?: string;
    target_count?: number;
    transitions?: boolean;
    workspace_id?: string;
}
export interface CloneBody {
    space_id?: string | null;
}
export interface CloneBrief {
    analysis?: "heuristic" | "llm";
    beats: Array<Beat>;
    caption_style: CaptionStyle;
    hook: Hook;
    keeps?: Array<string>;
    notes?: Array<string>;
    pacing: Pacing;
    setting?: string;
    source: SourceInfo;
    transcript?: string;
    version?: 1;
}
/**
 * The private template created by cloning a marketplace listing.
 */
export interface CloneData {
    id: string;
    name?: string;
    source_marketplace_id?: string;
    [key: string]: unknown;
}
/**
 * ``POST /api/v1/marketplace/{id}/clone`` — the caller's new private template.
 */
export interface CloneResponse {
    data: CloneData;
    message?: string | null;
    status?: number;
}
export interface CollectionCreate {
    title: string;
    title_ids?: Array<string>;
}
/**
 * Body for ``POST /motion/{preset_id}/compile``.
 */
export interface CompileMotionRequest {
    intensity?: number;
    preset_id?: string;
}
/**
 * Body for compile / instantiate — creator inputs + optional duration.
 */
export interface CompileRequest {
    character_id?: string | null;
    duration_s?: number | null;
    inputs?: {
        [key: string]: unknown;
    };
    surface?: string | null;
}
export interface Complete {
    cpu_seconds: number;
    files: Array<string>;
    measured_seconds?: number | null;
    packager_sha256: string;
}
export interface ConnectBody {
    api_key: string;
    domain?: string;
}
/**
 * ``GET /api/v1/me/connections`` — the caller's connected providers (token-free).
 *
 * ``data`` defaults to ``[]`` because the shared ``utils.get_response`` envelope
 * drops a falsy payload — a caller with no connections must still validate.
 */
export interface ConnectionListResponse {
    data?: Array<ConnectionModel>;
    message?: string | null;
    status?: number;
}
/**
 * One connected social account serialised to its TOKEN-FREE envelope.
 *
 * SECURITY: this shape NEVER carries an access or refresh token (encrypted or
 * not). Only the ``provider``, the provider-side ``external_account_id``, the
 * connection ``status`` (``connected`` | ``expired``), the granted ``scopes``
 * and the timestamps are exposed — enough for a "Connected accounts" UI, and
 * nothing a caller could use to impersonate the account. ``connected`` is a
 * convenience boolean (always ``True`` for a returned row).
 */
export interface ConnectionModel {
    connected?: boolean;
    connected_at?: string | null;
    external_account_id?: string;
    provider: string;
    scopes?: string;
    status?: string;
    token_expires_at?: string | null;
    updated_at?: string | null;
    [key: string]: unknown;
}
/**
 * ``GET/PUT /api/v1/me/consent`` — the caller's consent trail (or a decision).
 *
 * ``GET`` returns the caller's full trail as a list; ``GET?kind=`` returns the
 * current (newest) decision for that dimension (nullable); ``PUT`` records a new
 * decision and returns it. Always caller-scoped.
 */
export interface ConsentResponse {
    data?: unknown;
    message?: string | null;
    status?: number;
}
/**
 * Body for ``PUT /api/v1/me/consent`` — record a consent decision.
 *
 * ``kind`` is the consent dimension (required); ``granted`` records
 * grant/withdrawal; ``version`` is the policy version the decision was made
 * against. The decision is always recorded for the CALLER (never another user).
 */
export interface ConsentUpdateRequest {
    granted?: boolean;
    kind: string;
    version?: string;
}
export interface CouponCreate {
    amount_cents?: number | null;
    code: string;
    currency?: string | null;
    expires_at: string;
    kind: string;
    percent?: number | null;
}
/**
 * The generated cover descriptor returned to the client.
 *
 * ``cover_key`` is the persisted R2 object key; ``cover_url`` is a presigned
 * GET URL the UI can render/download immediately; ``style`` echoes the resolved
 * preset id that was rendered. ``auto_selected`` is ``True`` when the style was
 * auto-picked by the cover ranker (no explicit style supplied and a live
 * recommendation was available); ``recommendation`` carries the full ranked list
 * when the ranker ran (``null`` when there was no headline to rank on).
 */
export interface CoverData {
    auto_selected?: boolean;
    cover_key: string;
    cover_url: string;
    recommendation?: CoverRecommendation | null;
    style: string;
}
/**
 * The auto-pick result surfaced alongside a generated cover.
 *
 * ``recommended_style`` is the style the ranker would pick for the headline and
 * ``ranked`` is every candidate ordered best-first. ``degraded`` is ``True``
 * when no ``TYPESAFE_API_KEY`` is configured (or the ranker failed), in which
 * case the recommendation falls back to the deterministic default style.
 */
export interface CoverRecommendation {
    degraded: boolean;
    note?: string;
    ranked?: Array<RankedCoverStyle>;
    recommended_style: string;
}
/**
 * Request body for ``POST /api/v1/jobs/{job_id}/cover``.
 *
 * Both fields are optional. ``headline`` overrides the overlaid text; when
 * omitted the controller derives it from the job's script hook (its first
 * line) or the job's ``video_subject`` param. ``style`` selects a cover preset
 * (see ``GET /api/v1/catalog/cover-styles``); an unknown style is rejected with
 * HTTP 400 and an omitted style falls back to the default preset.
 */
export interface CoverRequest {
    headline?: string | null;
    style?: string | null;
}
/**
 * Envelope for a generated cover (``data`` carries the cover descriptor).
 */
export interface CoverResponse {
    data: CoverData;
    message?: string | null;
    status?: number;
}
/**
 * Cover-style catalog; ``data`` is a list of ``{id, name}`` descriptors.
 *
 * Defaults to ``[]`` so an empty/degraded catalog still validates against the
 * shared falsy-dropping ``get_response`` envelope.
 */
export interface CoverStylesResponse {
    data?: Array<{
        [key: string]: unknown;
    }>;
    message?: string | null;
    status?: number;
}
/**
 * Persisted ``AvatarPreset`` row serialised to the public envelope.
 *
 * ``provider_avatar_id`` carries HeyGen's ``talking_photo_id`` and ``kind`` is
 * ``"talking_photo"`` for a creator photo→avatar preset (mirrors
 * ``config['kind']``).
 */
export interface CreateAvatarData {
    display_name?: string;
    id: string;
    is_active?: boolean;
    kind?: string;
    provider: string;
    provider_avatar_id: string;
    thumbnail_url?: string;
    voice_name?: string;
    [key: string]: unknown;
}
/**
 * Request body for ``POST /api/v1/avatars`` (Phase 3 — custom avatar).
 *
 * Creates a USER photo→avatar preset from a previously uploaded selfie
 * (``image_key`` is the R2 key of the uploaded photo, which must be an upload
 * the caller owns). The image is turned into a HeyGen *talking-photo* avatar
 * that lip-syncs the reel's narration. ``display_name`` and ``voice_name``
 * (``"elevenlabs:<voice_id>"``) are optional metadata.
 */
export interface CreateAvatarRequest {
    display_name?: string | null;
    image_key: string;
    voice_name?: string | null;
}
export interface CreateAvatarResponse {
    data: CreateAvatarData;
    message?: string | null;
    status?: number;
}
export interface CreateExperimentBody {
    body_ref?: string;
    experiment_key: string;
    hook_refs?: Array<string>;
}
export interface CreatePostsBody {
    drafts: Array<DraftBody>;
    job_id: string;
    scheduled_at?: string | null;
}
/**
 * Start a repurpose job from an uploaded recording or an external URL.
 */
export interface CreateRepurposeRequest {
    language?: string;
    source_kind?: string;
    source_ref: string;
    title?: string;
}
/**
 * SAFE public creator profile (STRICT — no ``extra="allow"``).
 *
 * Contains a creator's public identity (handle / display_name / bio) plus their
 * PUBLIC reputation aggregates. It NEVER exposes credits, email, cost/revenue,
 * ``user_id`` or any other private field — the strict config drops anything
 * outside this allowlist. Mirrors ``app.services.creators.SAFE_PROFILE_FIELDS``.
 */
export interface CreatorProfileModel {
    avg_rating?: number;
    bio?: string;
    display_name?: string;
    follower_count?: number;
    following_count?: number;
    handle?: string;
    published_template_count?: number;
    total_clones_received?: number;
}
/**
 * ``GET /api/v1/creators/{handle_or_id}`` — a safe public profile.
 */
export interface CreatorProfileResponse {
    data: CreatorProfileModel;
    message?: string | null;
    status?: number;
}
/**
 * One cast or crew line (Wave Q QM1.5, U4).
 */
export interface Credit {
    name: string;
    role: string;
}
export interface CreditPackCheckoutRequest {
    channel?: "web" | "store";
    platform?: string | null;
    product_id?: string | null;
    transaction_id?: string | null;
}
/**
 * The raw query string Creem appended to our success URL.
 */
export interface CreemConfirmRequest {
    query: string;
}
export interface CsvBody {
    currency?: string;
    limit?: number;
    store_name?: string;
    text?: string | null;
    url?: string | null;
}
/**
 * The result of a self-service data export (GDPR Art. 15 / 20).
 *
 * ``download_url`` is a SHORT-LIVED presigned GET link to the caller's export
 * archive (a private R2 object, never public). ``expires_in`` is the link's
 * lifetime in seconds. The archive contains ONLY the requesting caller's own
 * data — no path can export another user's rows.
 */
export interface DataExportModel {
    download_url?: string;
    expires_in?: number;
}
/**
 * ``POST /api/v1/me/data-export`` — a short-lived signed download link.
 */
export interface DataExportResponse {
    data: DataExportModel;
    message?: string | null;
    status?: number;
}
export interface DecideBody {
    confirm_spend?: boolean;
    decision: "approve" | "reject" | "regenerate";
    note?: string;
    reason?: string;
}
/**
 * Create a shareable workspace, agent, or service receive identity.
 */
export interface DestinationProfileRequest {
    display_name: string;
    kind: "workspace" | "agent" | "service";
    slug: string;
    workspace_source_account_id?: string | null;
}
export interface DestinationProfileStateRequest {
    active: boolean;
}
export interface DetectBody {
    url: string;
}
/**
 * The caller's API-key footprint for the developer portal (SECRET-FREE).
 *
 * Counts only — never a raw key or hash. ``requests_this_month`` is the sum of
 * the current calendar month's request usage across all the caller's keys.
 */
export interface DeveloperApiKeysSummaryModel {
    active?: number;
    period_ym?: string;
    requests_this_month?: number;
    total?: number;
}
/**
 * ``GET /api/v1/me/developer`` — the caller-scoped API integration portal.
 *
 * A READ-only summary: the caller's API-key footprint, their webhook-subscription
 * footprint, the number of workspaces they belong to, and static integration
 * metadata (base URL, OpenAPI/docs links, API version, supported webhook events).
 * Key mint/revoke stays in the API-keys controller; subscription management in the
 * webhooks controller — this endpoint only links to them. NEVER carries a secret.
 */
export interface DeveloperPortalModel {
    api_base_url?: string;
    api_keys?: DeveloperApiKeysSummaryModel;
    api_version?: string;
    docs_url?: string;
    openapi_url?: string;
    webhook_event_types?: Array<string>;
    webhooks?: DeveloperWebhooksSummaryModel;
    workspaces?: number;
}
/**
 * ``GET /api/v1/me/developer`` — the caller's developer-portal summary.
 */
export interface DeveloperPortalResponse {
    data: DeveloperPortalModel;
    message?: string | null;
    status?: number;
}
/**
 * The caller's webhook-subscription footprint across their workspaces.
 *
 * Aggregated across every workspace the caller belongs to (tenant-scoped per
 * workspace). ``active`` counts only enabled subscriptions. No secret is exposed.
 */
export interface DeveloperWebhooksSummaryModel {
    active?: number;
    event_types?: Array<string>;
    total?: number;
}
/**
 * Proof the install is the real app on a real device (MN3).
 */
export interface DeviceAttestation {
    attestation?: string | null;
    challenge: string;
    integrity_token?: string | null;
    key_id?: string | null;
}
export interface DeviceChallengeRequest {
    install_id: string;
    platform: string;
}
export interface DeviceClaimRequest {
    device_api_key: string;
    install_id: string;
}
export interface DeviceSessionRequest {
    attestation?: DeviceAttestation | null;
    identity_token?: string | null;
    install_id: string;
    platform: string;
    supabase_access_token?: string | null;
}
export interface DiffusionBody {
    content_type?: "short_video" | "tutorial" | "product_demo" | "commentary";
    edges?: Array<DiffusionEdgeIn>;
    nodes: Array<DiffusionNodeIn>;
    seeds: Array<string>;
    steps?: number;
    trend_observation_id: string;
}
export interface DiffusionEdgeIn {
    probability: number;
    source: string;
    target: string;
}
export interface DiffusionNodeIn {
    audience_size: number;
    label?: string;
    node_id: string;
}
export interface DiscordBody {
    bot_token?: string;
    channel_id?: string;
    label?: string;
    webhook_url: string;
    workspace_id?: string | null;
}
export interface DismissBody {
    ad_ids?: Array<string>;
}
/**
 * Ids Dodo appended to our return URL (verified server-side with Dodo).
 */
export interface DodoConfirmRequest {
    payment_id?: string | null;
    subscription_id?: string | null;
}
export interface DraftBody {
    caption?: string;
    hashtags?: Array<string>;
    platform: string;
    title?: string;
}
export interface DraftCampaignBody {
    adam_id?: string;
    countries?: Array<string>;
    daily_budget_minor: number;
    name: string;
}
export interface DraftStatusBody {
    status: string;
}
/**
 * Envelope for a successful dub fan-out.
 *
 * ``batch_id`` is the single shared id linking the N dubbed jobs (one per
 * requested language) for joint review via ``GET /api/v1/batches/{batch_id}``;
 * ``job_ids`` and ``languages`` are positionally aligned (``job_ids[i]`` is the
 * job dubbing into ``languages[i]``).
 */
export interface DubData {
    batch_id: string;
    job_ids?: Array<string>;
    languages?: Array<string>;
    [key: string]: unknown;
}
/**
 * Request body for ``POST /api/v1/jobs/{job_id}/dub`` (multi-language dubbing).
 *
 * ``languages`` lists the target language codes to dub the source reel into —
 * the source SCRIPT is translated per language and the normal pipeline is
 * re-run (TTS via the ElevenLabs multilingual model, captions from the new
 * timestamps, avatar, compose) reusing the source's screen recording / avatar /
 * voice / layout / caption style. Every code is validated against
 * ``translate.is_supported_language`` at handler time (400 on any unknown /
 * empty code) and one credit is debited per language. The N dubbed jobs share
 * one ``batch_id`` so they surface together in ``GET /api/v1/batches/{id}``.
 */
export interface DubRequest {
    languages?: Array<string>;
}
/**
 * ``POST /api/v1/jobs/{job_id}/dub`` — the fanned-out multi-language batch.
 */
export interface DubResponse {
    data: DubData;
    message?: string | null;
    status?: number;
}
export interface DubVideoRequest {
    source_language: string;
    target_language: string;
    video_key: string;
    voice?: string | null;
    voice_engine?: string | null;
    whisper_model?: string | null;
}
export interface EditBody {
    caption?: string | null;
    hook?: string | null;
    slides?: Array<string> | null;
}
/**
 * Create an exact cut of a completed, caller-owned reel.
 */
export interface EditorExportRequest {
    in_point: number;
    out_point: number;
}
/**
 * The caller's active-plan entitlement bundle for a workspace.
 *
 * ``entitlements`` is the resolved ``{feature: value}`` map for the workspace's
 * LIVE plan (numeric limits like ``max_variants`` / ``seats`` /
 * ``monthly_credits`` and boolean capabilities like ``sso`` / ``api_access``). A
 * workspace with no live subscription resolves to the base/free plan.
 */
export interface EntitlementsModel {
    entitlements?: {
        [key: string]: unknown;
    };
    plan_key?: string;
    workspace_id: string;
    [key: string]: unknown;
}
/**
 * ``GET /api/v1/me/workspaces/{id}/entitlements`` — the caller's plan entitlements.
 */
export interface EntitlementsResponse {
    data: EntitlementsModel;
    message?: string | null;
    status?: number;
}
/**
 * Body for ``POST /api/v1/me/erase`` — a deliberate two-factor confirmation.
 *
 * Erasure is irreversible, so it requires an explicit ``confirm=true`` step;
 * a missing/false confirmation is rejected with HTTP 400 and nothing is erased.
 * The route only ever erases the CALLER'S OWN account (no target id is accepted),
 * so a user can never erase another account through this surface.
 */
export interface ErasureConfirmRequest {
    confirm?: boolean;
    confirmation?: string | null;
}
/**
 * A right-to-erasure request's public shape (GDPR Art. 17).
 *
 * ``status`` moves ``requested -> processing -> completed``. Erasure ANONYMIZES
 * PII in place (email/name/handle tombstoned, credentials revoked, job
 * scripts/prompts blanked) while PRESERVING legally-required financial / audit
 * records; it never cascade-deletes. ``scope`` records what was erased.
 */
export interface ErasureRequestModel {
    completed_at?: string | null;
    id?: string;
    requested_at?: string | null;
    scope?: string;
    status?: string;
    user_id?: string;
}
/**
 * ``POST /api/v1/me/erase`` — the caller's own completed erasure request.
 */
export interface ErasureRequestResponse {
    data: ErasureRequestModel;
    message?: string | null;
    status?: number;
}
export interface ExportBody {
    pages: Array<string>;
}
export interface FaceBody {
    space_id?: string | null;
}
export interface Failed {
    error: string;
}
export interface Files {
    files: Array<string>;
}
export interface FilmPlanBody {
    beats?: Array<BeatIn>;
    character: CharacterIn;
    target_runtime_s?: number | null;
    total_shots?: number;
}
export interface FolderBody {
    name: string;
    space_id?: string | null;
}
/**
 * ``POST``/``DELETE /api/v1/creators/{id}/follow`` — follow-state envelope.
 */
export interface FollowResponse {
    data: FollowResultModel;
    message?: string | null;
    status?: number;
}
/**
 * Result of a follow / unfollow (safe — only ``following`` state + counts).
 */
export interface FollowResultModel {
    follower_count?: number;
    following: boolean;
    removed?: boolean | null;
    [key: string]: unknown;
}
/**
 * ``GET /api/v1/me/following`` — safe public profiles the caller follows.
 */
export interface FollowingListResponse {
    data?: Array<CreatorProfileModel>;
    message?: string | null;
    status?: number;
}
export interface FormatCheckBody {
    drafts: Array<DraftBody>;
}
export interface GenerateBody {
    brand_kit_id?: string | null;
    prompt: string;
    size_preset?: string;
    use_llm?: boolean;
}
/**
 * Request body for ``POST /api/v1/ideas/generate``.
 *
 * ``app_context`` describes the creator's app/niche and is required; an empty
 * value is rejected with a clean ``400`` at the controller (not a ``422``) so
 * the error shape matches the rest of the API. ``count`` is clamped into
 * ``[1, 10]`` by the generator regardless of the value supplied here.
 */
export interface GenerateIdeasRequest {
    app_context?: string;
    audience?: string | null;
    count?: number | null;
    language?: string | null;
}
/**
 * Generation features available to the authenticated client.
 */
export interface GenerationCapabilities {
    broll: boolean;
    reels: boolean;
}
/**
 * A request for a generation price quote.
 *
 * Either name a curated/owned ``profile`` slug, or pass an ad-hoc
 * ``stages`` map of ``stage -> model_id``. ``estimates`` optionally overrides
 * the per-stage billed quantity; ``max_cost_usd`` is a caller budget cap
 * (decimal string, e.g. ``"2.50"``) checked against the resolved estimate.
 */
export interface GenerationQuoteRequest {
    estimates?: {
        [key: string]: number;
    } | null;
    max_cost_usd?: string | null;
    profile?: string | null;
    stages?: {
        [key: string]: string;
    } | null;
    workspace_id?: string | null;
}
export interface HTTPValidationError {
    detail?: Array<ValidationError>;
}
export interface Heartbeat {
    cores?: number;
    free_gb: number;
}
export interface Hook {
    end_s: number;
    framing?: "close" | "medium" | "wide" | "unknown";
    pattern?: "price_shock" | "question" | "pov" | "bold_claim" | "list" | "statement";
    summary?: string;
}
/**
 * Hook browser; ``data`` is a language-keyed map of native hook lines.
 *
 * Defaults to ``{}`` so a degraded/empty read still validates against the
 * shared falsy-dropping ``get_response`` envelope.
 */
export interface HookCatalogResponse {
    data?: {
        [key: string]: Array<string>;
    };
    message?: string | null;
    status?: number;
}
/**
 * First-3s signals (each 0..1) extracted by the client-side probe.
 */
export interface HookScoreBody {
    audio_onset?: number;
    early_cut?: number;
    face_or_subject?: number;
    hook_end_s?: number;
    motion?: number;
    opening_line?: string;
    speech?: number;
    text?: number;
}
export interface HookVariantIn {
    id: string;
    text: string;
}
export interface HormoziBody {
    highlight_hex?: string;
    max_per_group?: number;
    words?: Array<WordIn>;
}
/**
 * A single SPARK viral-UGC video concept (permissive; schema may grow).
 *
 * ``extra="allow"`` keeps the model forward-compatible with new concept fields
 * added by the generator without breaking this response contract.
 */
export interface IdeaData {
    angle?: string;
    est_duration_s?: number | null;
    format?: string;
    hook?: string;
    language?: string | null;
    script_outline?: Array<string>;
    suggested_caption_style?: string | null;
    suggested_layout?: string | null;
    title?: string;
    [key: string]: unknown;
}
/**
 * ``POST /api/v1/ideas/generate`` — the generated concepts.
 *
 * ``data`` defaults to ``[]`` because the shared ``utils.get_response``
 * envelope drops a falsy payload — an empty list must still validate.
 */
export interface IdeasResponse {
    data?: Array<IdeaData>;
    message?: string | null;
    status?: number;
}
export interface ImageRequest {
    image_key?: string;
    source_job_id?: string;
}
/**
 * Request body for ``POST /api/v1/admin/impersonate``.
 *
 * ``user_id`` is the target account a platform admin wishes to impersonate. An
 * unknown target is rejected with HTTP 400; a non-staff caller with HTTP 403.
 */
export interface ImpersonateRequest {
    user_id: string;
}
/**
 * Envelope for a minted, time-boxed impersonation grant (staff-only).
 *
 * ``data`` carries the opaque ``token`` plus ``admin_user_id``,
 * ``target_user_id``, ``scope``, ``issued_at``, ``expires_at`` and
 * ``expires_in`` (seconds). The action is recorded as an append-only
 * ``admin.impersonated`` audit row so every impersonation is accountable.
 */
export interface ImpersonationResponse {
    data?: unknown;
    message?: string | null;
    status?: number;
}
export interface ImportBody {
    limit?: number;
    provider?: string;
    store_url: string;
}
export interface Inputs {
    choice?: string;
    image_key?: string;
    image_key_2?: string;
    music_id?: string;
    text?: string;
    video_key?: string;
}
/**
 * A single creator's dashboard analytics (scoped to the caller).
 */
export interface InsightsData {
    avg_render_ms?: number;
    credits_balance?: number;
    credits_spent?: number;
    jobs_by_state?: {
        [key: string]: number;
    };
    jobs_total?: number;
    total_cost_usd?: number;
    user_id: string;
    videos_generated?: number;
    [key: string]: unknown;
}
/**
 * ``GET /api/v1/me/insights`` — per-user analytics summary.
 */
export interface InsightsResponse {
    data: InsightsData;
    message?: string | null;
    status?: number;
}
export interface InspirationBody {
    notes?: string;
    space_id?: string | null;
    title?: string;
    url: string;
}
/**
 * Request body for ``POST /api/v1/workspaces/{id}/invite``.
 *
 * ``email`` must resolve to an *existing* account (invites never create users);
 * an unknown email is rejected with HTTP 400. ``role`` is optional and defaults
 * to ``member`` when omitted; an invalid role is rejected with HTTP 400 and a
 * role above the caller's own is rejected with HTTP 403.
 */
export interface InviteRequest {
    email: string;
    role?: string | null;
}
/**
 * One line on an invoice (description + quantity + integer minor-unit amount).
 */
export interface InvoiceLineItemModel {
    amount_cents?: number;
    created_at?: string | null;
    description?: string;
    id: string;
    quantity?: number;
}
/**
 * A workspace's invoice (tenant-scoped; integer cents, never a float).
 *
 * ``amount_cents`` is the exact integer sum of the invoice's lines in
 * ``currency``. ``status`` is one of ``draft | open | paid | void``.
 */
export interface InvoiceModel {
    amount_cents?: number;
    created_at?: string | null;
    currency?: string;
    id: string;
    line_items?: Array<InvoiceLineItemModel>;
    period_end?: string | null;
    period_start?: string | null;
    provider_ref?: string;
    status?: string;
    workspace_id: string;
}
/**
 * ``GET /api/v1/me/workspaces/{id}/invoices`` — the workspace's invoices (newest first).
 */
export interface InvoicesResponse {
    data?: Array<InvoiceModel>;
    message?: string | null;
    status?: number;
}
export interface JobBody {
    job_id: string;
}
/**
 * Request body for ``POST /api/v1/jobs`` (§5.1).
 *
 * ``params`` carries a ``ReelForgeParams``-shaped mapping (validated by the
 * dataclass in ``app/services/reelforge.py`` at handler time). Optional
 * top-level ``avatar_id`` / ``voice_id`` overrides are folded into ``params``
 * by the controller.
 */
export interface JobCreateRequest {
    auto_tighten?: boolean;
    auto_zoom?: boolean;
    avatar_id?: string | null;
    bgm_provider?: string | null;
    broll_intro_key?: string | null;
    broll_outro_key?: string | null;
    camera_motion?: string | null;
    caption_style?: string | null;
    effects?: Array<string> | null;
    forecast_id?: string | null;
    music_id?: string | null;
    music_prompt?: string | null;
    params?: {
        [key: string]: unknown;
    };
    remove_bg?: boolean;
    source_id?: string | null;
    source_kind?: "trend" | null;
    source_label?: string | null;
    tos_disclosure?: boolean;
    variants?: number;
    vfx_intensity?: number;
    voice_id?: string | null;
    voiceover_key?: string | null;
    webhook_secret?: string | null;
    webhook_url?: string | null;
    workspace_id?: string | null;
    [key: string]: unknown;
}
/**
 * Public job status envelope (§5.1).
 *
 * Only ``job_id``/``state``/``progress`` are guaranteed on create; status
 * reads add ``stages`` and, when present, ``failed_stage`` / ``error`` /
 * ``result_url``.
 *
 * When a batch request fans out into multiple variants (``variants > 1``),
 * the create response carries every spawned job id in ``job_ids`` while
 * ``job_id`` stays populated with the first one for backward compatibility,
 * plus a shared ``batch_id`` linking the variants for joint review
 * (``GET /api/v1/batches/{batch_id}``); for a single job (``variants == 1``)
 * both ``job_ids`` and ``batch_id`` are left ``None``.
 */
export interface JobData {
    batch_id?: string | null;
    brief_ready?: boolean | null;
    correlation_id?: string | null;
    cover_key?: string | null;
    cover_url?: string | null;
    created_at?: string | null;
    error?: string | null;
    failed_stage?: string | null;
    hook?: string | null;
    job_id: string;
    job_ids?: Array<string> | null;
    kind?: string | null;
    language?: string | null;
    poster_key?: string | null;
    poster_url?: string | null;
    preview_key?: string | null;
    preview_url?: string | null;
    progress?: number;
    result_url?: string | null;
    retry_eligible?: boolean | null;
    source_footage_ready?: boolean | null;
    stages?: {
        [key: string]: unknown;
    } | null;
    state: number;
    [key: string]: unknown;
}
/**
 * Envelope for ``GET /api/v1/jobs`` — the caller's own jobs, newest first.
 */
export interface JobListData {
    jobs?: Array<JobData>;
    [key: string]: unknown;
}
export interface JobListResponse {
    data: JobListData;
    message?: string | null;
    status?: number;
}
/**
 * One logged reel outcome serialised to its public, caller-scoped envelope.
 */
export interface JobPerformanceModel {
    comments?: number;
    id: string;
    job_id: string;
    likes?: number;
    logged_at?: string | null;
    platform?: string;
    retention_pct?: number;
    saves?: number;
    shares?: number;
    updated_at?: string | null;
    views?: number;
    [key: string]: unknown;
}
export interface JobResponse {
    data: JobData;
    message?: string | null;
    status?: number;
}
/**
 * ``PATCH /jobs/{id}`` — rename and/or archive a reel.
 */
export interface JobUpdateRequest {
    archived?: boolean | null;
    title?: string | null;
}
export interface Latency {
    seconds: number;
}
export interface LaunchBody {
    audience?: AudienceBody;
    auto_optimize?: boolean;
    cta?: string;
    daily_budget_minor: number;
    headline?: string;
    landing_url?: string;
    name?: string;
    optimize_for?: string;
    platform: string;
    primary_text?: string;
    project_id: string;
    start_now?: boolean;
    variant_ids: Array<string>;
}
export interface LaunchVideoRequest {
    app_name?: string;
    app_url?: string;
    source?: string;
    token: string;
}
/**
 * Composition-layout catalog; ``data`` is a list of layout descriptors.
 */
export interface LayoutCatalogResponse {
    data?: Array<{
        [key: string]: unknown;
    }>;
    message?: string | null;
    status?: number;
}
export interface LeadBody {
    note?: string | null;
    status?: string | null;
}
/**
 * One ranked creator on the leaderboard (STRICT — safe fields only).
 *
 * Carries the safe profile aggregates plus the documented, deterministic
 * ``reputation_score``, the gaming-resistant ``win_score`` anchor, a 1-based
 * ``rank`` and the addressing ``user_id`` / ``handle``. It NEVER exposes
 * credits, email, cost/revenue or any other private field.
 */
export interface LeaderboardEntryModel {
    avg_rating?: number;
    display_name?: string;
    follower_count?: number;
    following_count?: number;
    handle?: string;
    published_template_count?: number;
    rank?: number;
    reputation_score?: number;
    total_clones_received?: number;
    user_id: string;
    win_score?: number;
}
/**
 * ``GET /api/v1/creators/leaderboard`` — creators ranked by a metric.
 */
export interface LeaderboardResponse {
    data?: Array<LeaderboardEntryModel>;
    message?: string | null;
    status?: number;
}
export interface LibraryPatch {
    folder_id?: string | null;
}
export interface LinearSave {
    ad_break_every?: number;
    name?: string | null;
    slug?: string | null;
    title_ids: Array<string>;
}
/**
 * Request body for ``POST /api/v1/jobs/{job_id}/performance``.
 *
 * All fields are optional so a creator can log a partial outcome (e.g. views +
 * retention only); an omitted field leaves the stored value untouched on
 * re-log. Every numeric field is validated at the controller boundary and
 * surfaces a clean ``400`` (not a ``422``) when out of range — counts must be
 * non-negative and ``retention_pct`` must lie in ``[0, 100]`` — matching the
 * error shape used across the rest of the API. ``platform`` is a short,
 * creator-entered persona string (e.g. ``tiktok`` | ``instagram`` | ``youtube``)
 * that the repository normalizes/lower-cases and bounds.
 */
export interface LogPerformanceRequest {
    comments?: number | null;
    likes?: number | null;
    platform?: string | null;
    retention_pct?: number | null;
    saves?: number | null;
    shares?: number | null;
    views?: number | null;
}
/**
 * Per-candidate-frame discontinuity scores (0 identical .. 1 hard seam).
 */
export interface LoopCheckBody {
    discontinuities?: Array<number>;
    fps?: number;
    max_discontinuity?: number | null;
    max_s?: number | null;
    min_s?: number;
    target_s?: number | null;
}
export interface LoopConfigBody {
    check_after_hours?: number | null;
    min_views?: number | null;
    mode: string;
    platforms?: Array<string>;
    spend_cap_credits?: number | null;
}
export interface ManualNetworkBody {
    current_daily_minor?: number;
    impressions?: number;
    network: string;
    results: number;
    spend_minor: number;
}
export interface ManualProduct {
    brand?: string;
    bullets?: Array<string>;
    currency?: string;
    description?: string;
    images?: Array<string>;
    language?: string;
    original_price?: number | null;
    price?: number | null;
    rating?: number | null;
    review_count?: number | null;
    reviews?: Array<string>;
    source?: string;
    title?: string;
}
/**
 * The remix-tree lineage of a listing: its ancestors + direct children.
 *
 * ``ancestors`` walks UP the ``parent_template_id`` chain (immediate parent
 * first → root); ``children`` are the DIRECT, still-published remixes
 * (newest-first). Every entry is a safe public ``MarketplaceTemplateModel``.
 */
export interface MarketplaceLineageData {
    ancestors?: Array<MarketplaceTemplateModel>;
    children?: Array<MarketplaceTemplateModel>;
    [key: string]: unknown;
}
/**
 * ``GET /api/v1/marketplace/{id}/lineage`` — ancestors + children.
 */
export interface MarketplaceLineageResponse {
    data: MarketplaceLineageData;
    message?: string | null;
    status?: number;
}
/**
 * ``GET /api/v1/marketplace`` — published listings, sorted + paginated.
 *
 * ``data`` defaults to ``[]`` because the shared ``utils.get_response`` envelope
 * drops a falsy payload — an empty result set must still validate.
 */
export interface MarketplaceListResponse {
    data?: Array<MarketplaceTemplateModel>;
    message?: string | null;
    status?: number;
}
/**
 * A public marketplace listing serialised to its JSON envelope.
 *
 * ``params`` is the opaque render-knob snapshot (caption_style, target_duration_s,
 * …) copied at publish time, so its shape can grow without a schema bump;
 * ``extra="allow"`` future-proofs the row shape (e.g. an optional ``viewer_stars``
 * the detail endpoint may attach for the caller's own rating). ``rating_avg`` /
 * ``rating_count`` are the denormalised aggregate maintained on each rating upsert.
 */
export interface MarketplaceTemplateModel {
    author_user_id?: string;
    clone_count?: number;
    created_at?: string | null;
    description?: string;
    id: string;
    language?: string;
    layout?: string;
    params?: {
        [key: string]: unknown;
    };
    parent_template_id?: string | null;
    prompt?: string;
    published?: boolean;
    rating_avg?: number;
    rating_count?: number;
    remix_count?: number;
    tags?: Array<string>;
    title?: string;
    updated_at?: string | null;
    win_score?: number | null;
    [key: string]: unknown;
}
/**
 * ``GET /api/v1/marketplace/{id}`` and publish/rate — a single listing.
 */
export interface MarketplaceTemplateResponse {
    data: MarketplaceTemplateModel;
    message?: string | null;
    status?: number;
}
export interface MastodonBody {
    access_token: string;
    instance: string;
    label?: string;
    visibility?: string;
    workspace_id?: string | null;
}
export interface MaterialInfo {
    duration?: number;
    provider?: string;
    source_info?: {
        [key: string]: unknown;
    } | null;
    url?: string;
}
/**
 * Authenticated user profile summary (§5.1).
 */
export interface MeData {
    credits?: number;
    email: string;
    is_staff?: boolean;
    jobs_count?: number;
    user_id: string;
    [key: string]: unknown;
}
export interface MeResponse {
    data: MeData;
    message?: string | null;
    status?: number;
}
export interface MedusaBody {
    base_url: string;
    limit?: number;
    publishable_key: string;
    storefront_url?: string;
}
export interface Member {
    email: string;
    role: string;
}
/**
 * Envelope for a single-member role read/change.
 *
 * ``data`` is one :class:`MemberRoleModel` descriptor (``{user_id, email, role,
 * created_at}``) — returned by ``PATCH /api/v1/me/workspaces/{id}/members/
 * {user_id}/role`` after a successful change. Typed as ``Any`` so the
 * falsy-dropping ``get_response`` envelope never trips response validation.
 */
export interface MemberRoleResponse {
    data?: unknown;
    message?: string | null;
    status?: number;
}
/**
 * Workspace member roster; ``data`` is a list of ``{user_id, email, role,
 * created_at}`` descriptors, oldest first (the owner leads).
 *
 * Defaults to ``[]`` so an empty/degraded roster still validates against the
 * shared falsy-dropping ``get_response`` envelope.
 */
export interface MembersResponse {
    data?: Array<{
        [key: string]: unknown;
    }>;
    message?: string | null;
    status?: number;
}
export interface MemoryBody {
    data: {
        [key: string]: unknown;
    };
}
export interface MessageBody {
    text: string;
}
/**
 * Per-metric usage vs plan limit for a billing period (integer units).
 *
 * ``limit`` is ``null`` when the metric is unbounded for the plan; ``overage`` is
 * ``max(0, used - limit)`` (0 when within allotment or unbounded).
 */
export interface MetricOverageModel {
    limit?: number | null;
    metric: string;
    overage?: number;
    used?: number;
}
export interface MetricsBody {
    avg_watch_frac?: number;
    completion_rate?: number | null;
    engagement_rate?: number;
    rewatch_rate?: number | null;
    views: number;
}
export interface MjTagRequest {
    key: string;
    product?: string;
    tag: string;
}
export interface MonthlyChangeRequest {
    plan_key: string;
}
export interface MonthlyCheckoutRequest {
    interval?: string;
    plan_key: string;
}
export interface MoveBody {
    force?: boolean;
    scheduled_at: string;
}
/**
 * Background-music catalog; ``data`` is a list of track descriptors.
 *
 * Defaults to ``[]`` so an empty songs directory (or a degraded read) still
 * validates against the shared falsy-dropping ``get_response`` envelope.
 */
export interface MusicCatalogResponse {
    data?: Array<{
        [key: string]: unknown;
    }>;
    message?: string | null;
    status?: number;
}
/**
 * AI-music generator catalog; ``data`` is a list of enabled providers.
 *
 * Each entry is ``{id, name, max_prompt_length}`` for an AI-BGM provider whose
 * credentials are configured (``is_enabled()``). Defaults to ``[]`` so a
 * deployment with no configured provider still validates against the shared
 * falsy-dropping ``get_response`` envelope — the UI hides "Generate with AI"
 * when the list is empty.
 */
export interface MusicGeneratorsResponse {
    data?: Array<{
        [key: string]: unknown;
    }>;
    message?: string | null;
    status?: number;
}
/**
 * A curated background-music track mixed under the produced output.
 *
 * ``music_id`` is a slug from the deployment catalog (``GET /catalog/music``);
 * it is validated for shape here (the same ``[a-z0-9-]`` slug the catalog can
 * mint) and resolved to a real file at render time. ``volume`` is a linear mix
 * gain (``1.0`` = unity); the renderer degrades to no music for an unknown id.
 */
export interface MusicTrackInput {
    music_id: string;
    volume?: number;
}
/**
 * A single cloned voice in the caller's library (``GET /voices/mine``).
 */
export interface MyVoiceItem {
    created_at?: string | null;
    id: string;
    name: string;
    status: string;
    voice_id: string;
    [key: string]: unknown;
}
export interface MyVoicesResponse {
    data?: Array<MyVoiceItem>;
    message?: string | null;
    status?: number;
}
/**
 * A native game running in a simulator/emulator on the capture host.
 */
export interface NativeBody {
    app_id?: string;
    deep_link?: string;
    device?: string;
    platform: "ios" | "android";
    settle_s?: number;
    title?: string;
}
/**
 * Request body for a native publish.
 */
export interface NativePublishBody {
    caption?: string;
    hashtags?: Array<string>;
    platform: string;
    privacy?: string;
    title?: string;
}
export interface NodeCreate {
    kind: string;
    name: string;
}
/**
 * One notification serialised to its public, caller-scoped envelope.
 *
 * ``data`` is the opaque, per-event payload (e.g. ``job_id``, ``result_url``,
 * ``error``, ``balance``, ``credits``); its shape can grow without a schema
 * change, so it stays a permissive JSON map. ``extra="allow"`` future-proofs
 * the row shape without forcing a model bump.
 */
export interface NotificationData {
    body?: string;
    created_at?: string | null;
    data?: {
        [key: string]: unknown;
    };
    id: string;
    kind: string;
    read?: boolean;
    title: string;
    [key: string]: unknown;
}
export interface NotificationsData {
    notifications?: Array<NotificationData>;
    unread_count?: number;
}
/**
 * ``GET /api/v1/me/notifications`` — the caller's notifications + unread count.
 *
 * ``data`` is an object carrying the (newest-first) notification list plus the
 * caller's live ``unread_count`` so the client can render the list and refresh
 * the bell badge from a single call.
 */
export interface NotificationsResponse {
    data: NotificationsData;
    message?: string | null;
    status?: number;
}
export interface NumbersBody {
    comments?: number | null;
    likes?: number | null;
    saves?: number | null;
    shares?: number | null;
    views?: number | null;
}
export interface OfferCreate {
    currency?: string;
    interval?: string | null;
    kind: string;
    name: string;
    price_cents: number;
    rental_hours?: number | null;
    title_id?: string | null;
}
export interface OriginalRequest {
    narrator_id: string;
}
export interface OverageBody {
    opt_in: boolean;
}
export interface Pacing {
    avg_beat_s: number;
    avg_shot_s: number;
    beat_count: number;
    cuts_per_10s: number;
    music_bpm?: number | null;
    onsets_s?: Array<number>;
    shot_count: number;
}
export interface PainPointSearchBody {
    limit?: number;
    product_name?: string;
    query: string;
    subreddits?: Array<string>;
}
/**
 * ``GET /api/v1/me/performance`` — the caller's logged reel outcomes.
 *
 * ``data`` defaults to ``[]`` because the shared ``utils.get_response`` envelope
 * drops a falsy payload — an empty list must still validate.
 */
export interface PerformanceListResponse {
    data?: Array<JobPerformanceModel>;
    message?: string | null;
    status?: number;
}
/**
 * Caller's effective permissions in a workspace.
 *
 * ``data`` carries ``{"workspace_id", "role", "permissions": [<perm>, ...]}`` —
 * the permissions the caller's role grants (direct + inherited) as computed by
 * :func:`app.services.rbac.effective_permissions`. ``role`` is ``null`` and
 * ``permissions`` empty when the caller is not a member of the workspace (no
 * tenant leak).
 */
export interface PermissionsResponse {
    data?: unknown;
    message?: string | null;
    status?: number;
}
/**
 * Shared read-only capability document for every first-party client.
 */
export interface PilotCapabilities {
    canonical_routes: CanonicalGenerationRoutes;
    engine?: {
        [key: string]: unknown;
    };
    generation: GenerationCapabilities;
    launch?: {
        [key: string]: unknown;
    };
    limits: PilotLimits;
    mode: "internal_pilot" | "standard";
    product?: {
        [key: string]: unknown;
    };
}
export interface PilotCapabilitiesResponse {
    data: PilotCapabilities;
    message?: string | null;
    status?: number;
}
/**
 * Non-sensitive pilot limits suitable for client presentation.
 */
export interface PilotLimits {
    max_credits_per_request?: number | null;
    pilot_enabled: boolean;
}
/**
 * Public description of a purchasable credit plan (§ billing).
 *
 * ``credits`` are locked by contract; ``price_usd`` and provider ids may be
 * overridden via config. Extra provider fields (``stripe_price_id``,
 * ``iyzico_amount``, ``is_purchasable``) are allowed through for clients that
 * render them.
 */
export interface Plan {
    credits: number;
    display_name: string;
    key: string;
    price_usd?: number;
    [key: string]: unknown;
}
/**
 * Public credit-plan catalogue; ``data`` is a list of plans.
 */
export interface PlansResponse {
    data: Array<Plan>;
    message?: string | null;
    status?: number;
}
export interface PlatformStatusBody {
    note?: string;
    platform_id: string;
    product_name: string;
    status: string;
}
export interface PlayAppBody {
    package_name: string;
}
export interface PlayConnectBody {
    service_account_json: string;
}
export interface PlayRequest {
    previous_token?: string;
    viewer_id?: string;
}
export interface PremiumCheckoutRequest {
    pack_key: string;
}
/**
 * Body for ``POST /me/presets`` with an optional shared ``workspace_id``.
 */
export interface PresetCreateBody {
    config?: {
        [key: string]: unknown;
    };
    name?: string;
    workspace_id?: string | null;
    [key: string]: unknown;
}
/**
 * A saved user preset serialised to the public envelope (caller-scoped).
 */
export interface PresetData {
    config?: {
        [key: string]: unknown;
    };
    created_at?: string | null;
    id: string;
    name: string;
    [key: string]: unknown;
}
/**
 * ``DELETE /api/v1/me/presets/{id}`` — deletion acknowledgement.
 */
export interface PresetDeleteResponse {
    data?: unknown;
    message?: string | null;
    status?: number;
}
/**
 * ``GET /api/v1/me/presets`` — the caller's saved presets, newest first.
 *
 * ``data`` defaults to ``[]`` because the shared ``utils.get_response``
 * envelope drops a falsy payload — an empty list must still validate.
 */
export interface PresetListResponse {
    data?: Array<PresetData>;
    message?: string | null;
    status?: number;
}
/**
 * Body of ``POST /jobs/quote/preset`` (MH1).
 */
export interface PresetQuoteRequest {
    preset_sku: string;
    resolution?: string | null;
    seconds?: number;
    tier?: string;
    variants?: number;
}
/**
 * ``POST /api/v1/me/presets`` — a single saved preset.
 */
export interface PresetResponse {
    data: PresetData;
    message?: string | null;
    status?: number;
}
/**
 * Presigned upload payload returned to the client (§5.1).
 */
export interface PresignData {
    get_url: string;
    headers?: {
        [key: string]: string;
    };
    key: string;
    upload_url: string;
    [key: string]: unknown;
}
/**
 * Request body for ``POST /api/v1/uploads/presign`` (§5.1).
 */
export interface PresignRequest {
    content_type: string;
    filename: string;
    size: number;
}
export interface PresignResponse {
    data: PresignData;
    message?: string | null;
    status?: number;
}
export interface ProductShotsRequest {
    keys?: Array<string>;
}
/**
 * Request body for ``PATCH /api/v1/me/profile`` (set handle/display_name/bio).
 *
 * Every field is optional — only the ones the caller sets are updated. ``handle``
 * is normalised to a lowercase slug and validated for shape (a taken handle is a
 * clean ``409`` at the controller). All three are safe, public identity fields.
 */
export interface ProfileUpdateRequest {
    bio?: string | null;
    display_name?: string | null;
    handle?: string | null;
}
/**
 * ``PATCH /api/v1/me/profile`` — the caller's updated public profile.
 */
export interface ProfileUpdateResponse {
    data: CreatorProfileModel;
    message?: string | null;
    status?: number;
}
export interface Progress {
    device?: string;
    duration_s?: number;
    position_s: number;
}
export interface ProjectsBody {
    language?: string | null;
    product_ids: Array<string>;
    use_llm?: boolean;
}
/**
 * Enabled payment providers payload for the checkout UI.
 *
 * ``providers`` lists the provider ids (subset of ``stripe`` / ``iyzico`` /
 * ``creem`` / ``polar``) whose required secrets are configured, so the client
 * renders only the rails that will actually work.
 */
export interface ProvidersData {
    providers: Array<string>;
    [key: string]: unknown;
}
/**
 * Enabled payment providers; ``data.providers`` is a list of provider ids.
 */
export interface ProvidersResponse {
    data: ProvidersData;
    message?: string | null;
    status?: number;
}
export interface PublishAll {
    limit?: number;
}
/**
 * Publish results envelope; ``data`` carries the per-platform outcomes.
 */
export interface PublishResponse {
    data?: unknown;
    message?: string | null;
    status?: number;
}
/**
 * The outcome of a direct publish to a connected provider (token-free).
 */
export interface PublishResultModel {
    external_post_id?: string;
    provider: string;
    status?: string;
    url?: string;
    [key: string]: unknown;
}
/**
 * ``POST /api/v1/jobs/{id}/publish/{provider}`` — the direct-publish result.
 */
export interface PublishResultResponse {
    data: PublishResultModel;
    message?: string | null;
    status?: number;
}
/**
 * Request body for ``POST /api/v1/marketplace/publish``.
 *
 * Two ways to publish, both owner-scoped:
 *
 * * Reference an existing private template via ``template_id`` (a
 *   :class:`UserPreset` OWNED by the caller) to snapshot its ``name`` + config;
 *   a foreign/missing id is a clean ``404``. Explicit inline fields override the
 *   values pulled from the referenced preset.
 * * Omit ``template_id`` and pass the snapshot inline. A ``title`` (inline or
 *   derived from the preset) is required — an empty resolved title is a ``400``.
 *
 * The published listing is an IMMUTABLE COPY: a later edit to the source private
 * template never mutates the public listing.
 */
export interface PublishTemplateRequest {
    description?: string | null;
    language?: string | null;
    layout?: string | null;
    params?: {
        [key: string]: unknown;
    } | null;
    prompt?: string | null;
    tags?: Array<string> | null;
    template_id?: string | null;
    title?: string | null;
}
/**
 * Request to ingest (scrape) a trend into the durable feed.
 */
export interface PullBody {
    kind?: string;
    max_posts?: number;
    target: string;
}
/**
 * Request a checkout quote for a wallet top-up (no charge is made).
 */
export interface PurchaseQuoteRequest {
    amount_usd: string;
}
export interface PushOptIn {
    platform?: string;
    token: string;
    topics: Array<string>;
}
export interface PushOptOut {
    token?: string;
}
/**
 * Body for ``POST /me/push-tokens`` (mobile push registration).
 *
 * Matches the mobile client's payload exactly
 * (``lib/api.ts::registerPushToken``): the Expo push token, the device
 * platform, and the stable SecureStore install id used as the UPSERT key. The
 * ``expo_token`` is SENSITIVE and is never logged. Bounds mirror the DB column
 * limits so an oversized value fails validation rather than at the DB.
 */
export interface PushTokenRegisterBody {
    expo_token: string;
    install_id: string;
    platform?: string;
}
export interface Question {
    question: string;
}
export interface QuoteBody {
    base_cost_micros: number;
}
export interface QuotedCredits {
    ai_video_credits?: number;
    standard_credits: number;
}
export interface RankBody {
    limit?: number;
    trends?: Array<TrendIn>;
}
export interface RankHooksBody {
    audience?: string;
    brand_voice?: string;
    platform?: string;
    topic?: string;
    variants: Array<HookVariantIn>;
}
export interface RankKeywordsBody {
    country?: string;
    keywords: Array<string>;
}
/**
 * Rank a job's transcript into highlight clips.
 *
 * Pass pre-scored ``segments`` for deterministic selection, or unscored
 * segments to have the ranker score them. ``max_clips`` / length band /
 * ``min_score`` tune the selection.
 */
export interface RankRequest {
    max_clips?: number;
    max_len_s?: number;
    min_len_s?: number;
    min_score?: number;
    segments?: Array<TranscriptSegment>;
}
/**
 * One catalog style scored by the cover ranker for the reel's headline.
 *
 * ``composite`` is the ranker's tunable score (``stop + 0.5*legibility -
 * 0.75*generic``); the raw ``stop_power`` / ``legibility`` / ``is_generic``
 * signals let a picker explain the ranking. ``scored`` is ``False`` for a
 * pass-through (degraded) entry with null signals.
 */
export interface RankedCoverStyle {
    composite: number;
    id: string;
    is_generic: number;
    legibility: number;
    name: string;
    primary_mood?: string;
    scored?: boolean;
    stop_power: number;
}
/**
 * Request body for ``POST /api/v1/marketplace/{id}/rate``.
 *
 * ``stars`` is a 1..5 rating. Exactly one rating exists per ``(user, template)``
 * — re-rating upserts the caller's existing row rather than adding a duplicate.
 * A value outside ``[1, 5]`` is rejected by the controller with a clean ``400``
 * (matching the rest of the API's error shape) rather than a raw ``422``.
 */
export interface RateRequest {
    stars: number;
}
export interface RealFaceRequest {
    consent_token: string;
    name?: string;
    passport_id: string;
    passport_version: number;
    recording_key: string;
    reference_keys: Array<string>;
    self_declared?: boolean;
}
/**
 * Provision or replay the stable public address for one wallet source.
 */
export interface ReceiveAddressRequest {
    source_account_id: string;
}
export interface RecordingDone {
    key: string;
    path: string;
    seconds: number;
    short_side?: number;
}
export interface RecreateRequest {
    image_key?: string | null;
    subject: string;
}
export interface RedditIngestRequest {
    subject?: string | null;
    url: string;
    voice_id?: string | null;
}
/**
 * Request body for ``POST /api/v1/me/referral/redeem``.
 *
 * ``code`` is another user's referral code. Redemption grants credits to both
 * the referrer and the redeeming (referee) user, guarded against self-referral
 * and double-redemption by :func:`app.services.referrals.redeem_referral`.
 */
export interface RedeemRequest {
    code: string;
}
/**
 * ``POST /api/v1/me/referral/redeem`` — redemption result envelope.
 */
export interface RedeemResponse {
    data?: unknown;
    message?: string | null;
    status?: number;
}
export interface ReferenceBody {
    content_type?: string;
    height?: number;
    r2_key: string;
    role?: string;
    width?: number;
}
/**
 * A user's referral code and lifetime referral performance.
 */
export interface ReferralData {
    code: string;
    credits_earned?: number;
    referred_count?: number;
    [key: string]: unknown;
}
/**
 * ``GET /api/v1/me/referral`` — the caller's referral code + stats.
 */
export interface ReferralResponse {
    data: ReferralData;
    message?: string | null;
    status?: number;
}
export interface RefreshBody {
    ad_account_id?: string | null;
    days?: number;
}
export interface RegenerateBody {
    angle_count?: number;
    use_llm?: boolean;
}
export interface RegisterRunBody {
    body_ref?: string;
    variants: Array<RunVariantBody>;
}
/**
 * The persisted asset id + key for a registered upload.
 */
export interface RegisterUploadData {
    asset_id: string;
    key: string;
    kind?: string;
    [key: string]: unknown;
}
/**
 * Request body for ``POST /api/v1/uploads/register``.
 *
 * Records a freshly-uploaded object (an ``uploads/<uuid>`` key from
 * {@link presign}) as an :class:`Asset` OWNED by the caller, so a later feature
 * (custom avatar, i2v B-roll reference) can verify ownership via the BOLA guard.
 * ``key`` MUST be in the non-enumerable ``uploads/`` namespace — a ``jobs/...``
 * artifact key is rejected so a caller can never claim another creator's
 * per-job output as their own upload.
 */
export interface RegisterUploadRequest {
    key: string;
    kind?: string;
}
export interface RegisterUploadResponse {
    data: RegisterUploadData;
    message?: string | null;
    status?: number;
}
export interface RemixRequest {
    job_id: string;
}
export interface Rename {
    display_name: string;
}
export interface RenameProjectBody {
    title: string;
}
export interface RenderBody {
    size?: string;
    video?: boolean;
}
export interface RenderRequest {
    dry_run?: boolean;
    engine?: string | null;
    plan: {
        [key: string]: unknown;
    };
}
export interface RenderShotBody {
    backend?: string;
    max_cost_micros?: number;
    rerender?: boolean;
    workspace_id?: string | null;
}
export interface ReplyBody {
    text: string;
}
export interface ReportRequest {
    content: string;
    details?: string;
    email: string;
    reason: string;
}
/**
 * Optional per-field tweaks applied when re-running a job (Phase 6).
 *
 * Every field is optional; only the ones a client sets replace the source
 * job's stored value. ``voice_id`` is normalised to the ``elevenlabs:<id>``
 * ``voice_name`` form by the controller (matching ``JobCreateRequest``).
 */
export interface RerunOverrides {
    avatar_id?: string | null;
    caption_style?: string | null;
    hook_style?: string | null;
    language?: string | null;
    layout?: string | null;
    music_id?: string | null;
    voice_id?: string | null;
}
/**
 * Request body for ``POST /api/v1/jobs/{job_id}/rerun`` (Phase 6).
 *
 * ``overrides`` is optional: an empty/absent body re-runs the source job with
 * its original params (a clean re-render), while any supplied field tweaks the
 * corresponding param on the new job.
 */
export interface RerunRequest {
    overrides?: RerunOverrides | null;
}
/**
 * Request body for ``PATCH /api/v1/me/calendar/{schedule_id}``.
 *
 * ``scheduled_at`` is the new target time as an ISO-8601 UTC timestamp (a
 * trailing ``Z`` is accepted; a naive value is treated as UTC).
 */
export interface RescheduleRequest {
    scheduled_at: string;
}
/**
 * ``PATCH /api/v1/me/calendar/{schedule_id}`` — the moved schedule.
 */
export interface RescheduleResponse {
    data?: CalendarEntryModel | null;
    message?: string | null;
    status?: number;
}
export interface ResearchBody {
    seeds: Array<string>;
}
/**
 * A workspace's data-retention window (GDPR retention).
 *
 * ``jobs_retention_days`` / ``assets_retention_days`` bound how long a
 * workspace's members' jobs / assets are kept before the periodic sweep
 * anonymizes the aged rows. ``None`` means **keep forever** (that dimension is
 * never swept). Reading/writing a policy is gated on ``workspace.settings``.
 */
export interface RetentionPolicyModel {
    assets_retention_days?: number | null;
    created_at?: string | null;
    jobs_retention_days?: number | null;
    updated_at?: string | null;
    workspace_id?: string;
}
/**
 * ``GET/PUT /api/v1/me/workspaces/{id}/retention`` — a workspace policy.
 */
export interface RetentionPolicyResponse {
    data: RetentionPolicyModel;
    message?: string | null;
    status?: number;
}
/**
 * Body for ``PUT /api/v1/me/workspaces/{id}/retention`` — set the window.
 *
 * A full replace of both windows: ``None`` (or omitted) means **keep forever**
 * for that dimension; a negative value is rejected (HTTP 400). Only a workspace
 * owner/admin (``workspace.settings``) may set it — a viewer gets HTTP 403.
 */
export interface RetentionUpdateRequest {
    assets_retention_days?: number | null;
    jobs_retention_days?: number | null;
}
/**
 * Platform revenue summary (cross-tenant; ``is_staff`` ONLY).
 *
 * ``revenue_cents`` is the integer sum of realized (``paid``) invoices across all
 * tenants since the cutoff; ``credits_granted`` is the outstanding liability side
 * (total credits granted); ``net_cents`` mirrors realized revenue.
 */
export interface RevenueModel {
    credits_granted?: number;
    net_cents?: number;
    revenue_cents?: number;
}
/**
 * ``GET /api/v1/admin/revenue`` — platform-wide revenue summary (staff-only).
 */
export interface RevenueResponse {
    data: RevenueModel;
    message?: string | null;
    status?: number;
}
export interface Review {
    approve: boolean;
}
export interface ReviewBody {
    avg_watch_frac?: number;
    engagement_rate?: number;
    geo_concentration?: number;
    override_hold?: boolean;
    retention_cliff?: number;
    velocity_zscore?: number;
    views: number;
}
/**
 * Request body for ``POST /api/v1/workspaces/{id}/members/{user_id}/role``.
 *
 * ``role`` is the new role for the target member (``owner | admin | member``);
 * an invalid role is rejected with HTTP 400.
 */
export interface RoleRequest {
    role: string;
}
/**
 * Request body for ``PATCH /api/v1/me/workspaces/{id}/members/{user_id}/role``.
 *
 * ``role`` is the new Enterprise role for the target member
 * (``owner | admin | editor | viewer | billing``). An unknown role is rejected
 * with HTTP 400; a role above the caller's own rank, or a change that would
 * demote the workspace's last ``owner``, is rejected with HTTP 403 / 409.
 */
export interface RoleUpdateRequest {
    role: string;
}
export interface RoutineBody {
    count?: number | null;
    hour?: number | null;
    name?: string;
    skill?: string | null;
    space_id?: string | null;
    text?: string | null;
    weekday?: number | null;
}
export interface RoutinePatch {
    count?: number | null;
    enabled?: boolean | null;
    hour?: number | null;
}
/**
 * Trigger one unattended render pass over an inline source list.
 *
 * Mirrors the publicly-configurable surface of ``ChannelRunConfig``; the
 * ``channel_id`` comes from the path and ``user_id`` from the caller.
 */
export interface RunChannelRequest {
    accounts?: Array<string>;
    aspects?: Array<string>;
    hooks?: Array<string>;
    max_per_account?: number | null;
    max_words?: number | null;
    platforms?: Array<string>;
    source_items?: Array<SourceItemIn>;
    subject?: string;
    template_slug?: string;
    voice_id?: string | null;
}
export interface RunVariantBody {
    hook_style?: string;
    job_id: string;
}
/**
 * ``PUT /api/v1/me/workspaces/{id}/sso`` body — configure the IdP connection.
 *
 * ``idp_x509_cert`` (SAML signing cert) and ``oidc_client_secret`` are
 * WRITE-ONLY: they are Fernet-encrypted at the service boundary and never
 * returned. ``protocol`` must be one of ``saml`` | ``oidc``.
 */
export interface SSOConfigRequest {
    enabled?: boolean;
    idp_entity_id?: string;
    idp_sso_url?: string;
    idp_x509_cert?: string;
    oidc_client_id?: string;
    oidc_client_secret?: string;
    protocol?: string;
    sp_acs_url?: string;
}
/**
 * CERT-FREE public view of a workspace's Enterprise SSO connection.
 *
 * The IdP signing certificate and OIDC client secret are NEVER included — only
 * ``has_certificate`` / ``has_client_secret`` booleans report whether a secret is
 * configured. Safe to return from the admin config surface.
 */
export interface SSOConnectionModel {
    created_at?: string | null;
    enabled?: boolean;
    has_certificate?: boolean;
    has_client_secret?: boolean;
    idp_entity_id?: string;
    idp_sso_url?: string;
    oidc_client_id?: string | null;
    protocol?: string;
    sp_acs_url?: string;
    sp_metadata_url?: string;
    updated_at?: string | null;
    workspace_id: string;
}
/**
 * ``GET/PUT /api/v1/me/workspaces/{id}/sso`` — the cert-free connection status.
 *
 * ``data`` is ``null`` when the workspace has no SSO connection configured.
 */
export interface SSOConnectionResponse {
    data?: SSOConnectionModel | null;
    message?: string | null;
    status?: number;
}
/**
 * The SP-initiated login redirect target (the IdP SSO URL with a SAMLRequest).
 */
export interface SSOLoginModel {
    redirect_url: string;
    workspace_id: string;
}
/**
 * ``GET /api/v1/sso/{workspace_id}/login`` — where to send the browser (IdP).
 */
export interface SSOLoginResponse {
    data: SSOLoginModel;
    message?: string | null;
    status?: number;
}
/**
 * SP (service-provider) SAML metadata descriptor for a workspace.
 */
export interface SSOMetadataModel {
    acs_url: string;
    entity_id: string;
    metadata_xml: string;
    workspace_id: string;
}
/**
 * ``GET /api/v1/sso/{workspace_id}/metadata`` — the SP metadata (also served raw).
 */
export interface SSOMetadataResponse {
    data: SSOMetadataModel;
    message?: string | null;
    status?: number;
}
/**
 * The ReelForge session grant issued after a VALIDATED SAML assertion.
 *
 * ``session_token`` is an opaque bearer credential minted by the ACS controller
 * from the validated grant — it is never derived from an unsigned/foreign
 * assertion (any validation failure is a ``401`` and mints nothing).
 */
export interface SSOSessionModel {
    email: string;
    is_new_user?: boolean;
    role: string;
    session_token: string;
    token_type?: string;
    user_id: string;
    workspace_id: string;
}
/**
 * ``POST /api/v1/sso/{workspace_id}/acs`` — the issued session on success.
 */
export interface SSOSessionResponse {
    data: SSOSessionModel;
    message?: string | null;
    status?: number;
}
/**
 * Request body for ``POST /api/v1/me/ideas``.
 *
 * ``idea`` is the opaque concept dict to persist for the caller (typically one
 * item straight out of ``POST /ideas/generate``). It is stored whole; ``title``
 * and ``hook`` are denormalised out of it by the repository for list rendering.
 */
export interface SaveIdeaRequest {
    idea?: {
        [key: string]: unknown;
    };
}
/**
 * A saved SPARK concept serialised to the public envelope (caller-scoped).
 */
export interface SavedIdeaData {
    created_at?: string | null;
    hook?: string;
    id: string;
    idea?: {
        [key: string]: unknown;
    };
    title?: string;
    [key: string]: unknown;
}
/**
 * ``GET /api/v1/me/ideas`` — the caller's saved concepts, newest first.
 *
 * ``data`` defaults to ``[]`` because the shared ``utils.get_response``
 * envelope drops a falsy payload — an empty list must still validate.
 */
export interface SavedIdeasResponse {
    data?: Array<SavedIdeaData>;
    message?: string | null;
    status?: number;
}
export interface SavedRecipientRequest {
    label?: string;
    recipient_handle: string;
    source_account_id: string;
}
export interface SceneRequest {
    character_id: string;
    product_key?: string;
    quoted_credits: number;
    script: string;
}
/**
 * Trigger one publish-pacing pass over a channel's COMPLETE clips.
 *
 * ``platforms`` seeds the cross-post targets for clips whose stored platform is
 * blank (mirrors the runner's fallback to ``config.platforms[0]``).
 */
export interface ScheduleChannelRequest {
    accounts?: Array<string>;
    platforms?: Array<string>;
}
/**
 * Request body for ``POST /api/v1/jobs/{job_id}/schedule``.
 *
 * Queues a *completed* job to auto-publish to social platforms at a future UTC
 * time. ``platforms`` selects the targets (subset of
 * ``tiktok | instagram | youtube_shorts``); ``scheduled_at`` is an ISO-8601 UTC
 * timestamp; ``youtube_privacy_status`` optionally overrides YouTube visibility.
 */
export interface ScheduleRequest {
    platforms?: Array<string>;
    scheduled_at: string;
    youtube_privacy_status?: string | null;
}
/**
 * A single scheduled-publish row serialised to the public envelope.
 *
 * ``extra="allow"`` so a partial projection (e.g. the ``POST`` result carrying
 * only ``id`` / ``scheduled_at`` / ``status``) still validates, while list rows
 * may additionally surface ``job_id`` / ``platforms`` / lifecycle metadata.
 */
export interface ScheduledData {
    id: string;
    job_id?: string | null;
    platforms?: Array<string>;
    scheduled_at?: string | null;
    status?: string;
    [key: string]: unknown;
}
/**
 * ``GET /api/v1/me/scheduled`` — the caller's schedules, soonest-due first.
 *
 * ``data`` defaults to ``[]`` because the shared ``utils.get_response`` envelope
 * drops a falsy payload — an empty list must still validate.
 */
export interface ScheduledListResponse {
    data?: Array<ScheduledData>;
    message?: string | null;
    status?: number;
}
/**
 * ``POST /api/v1/jobs/{job_id}/schedule`` — the created schedule.
 */
export interface ScheduledResponse {
    data?: ScheduledData | null;
    message?: string | null;
    status?: number;
}
/**
 * ``POST /api/v1/me/workspaces/{id}/scim/tokens`` — the freshly minted token.
 *
 * The raw ``token`` is present here EXACTLY ONCE; store it now — it can never be
 * retrieved again.
 */
export interface ScimTokenCreatedResponse {
    data: ScimTokenModel;
    message?: string | null;
    status?: number;
}
/**
 * ``GET /api/v1/me/workspaces/{id}/scim/tokens`` — the workspace's tokens.
 *
 * Never carries a raw token — only ids, prefixes, and status. Defaults to ``[]``.
 */
export interface ScimTokenListResponse {
    data?: Array<ScimTokenModel>;
    message?: string | null;
    status?: number;
}
/**
 * A workspace's SCIM bearer token descriptor.
 *
 * The raw ``token`` is populated ONLY in the mint response (shown once, then
 * unrecoverable); a listing carries ``token=None`` and only the non-secret
 * ``prefix``.
 */
export interface ScimTokenModel {
    created_at?: string | null;
    id: string;
    last_used_at?: string | null;
    prefix?: string;
    revoked?: boolean;
    token?: string | null;
    workspace_id: string;
}
export interface ScoreRequest {
    job_id: string;
    model?: string;
    preset_id?: string;
}
/**
 * A workspace's enterprise login security policy (cert-free, no secrets).
 */
export interface SecurityPolicyModel {
    allowed_email_domains?: Array<string>;
    created_at?: string | null;
    ip_allowlist?: Array<string>;
    mfa_required?: boolean;
    require_sso?: boolean;
    session_timeout_min?: number;
    updated_at?: string | null;
    workspace_id: string;
}
/**
 * ``PUT /api/v1/me/workspaces/{id}/security`` body — partial policy update.
 *
 * Every field is optional; only supplied (non-``None``) fields are applied, so a
 * caller can toggle a single rule without resending the whole policy.
 */
export interface SecurityPolicyRequest {
    allowed_email_domains?: Array<string> | null;
    ip_allowlist?: Array<string> | null;
    mfa_required?: boolean | null;
    require_sso?: boolean | null;
    session_timeout_min?: number | null;
}
/**
 * ``GET/PUT /api/v1/me/workspaces/{id}/security`` — the workspace policy.
 *
 * ``data`` is ``null`` when no policy has been configured yet.
 */
export interface SecurityPolicyResponse {
    data?: SecurityPolicyModel | null;
    message?: string | null;
    status?: number;
}
export interface SeoBody {
    base_caption?: string;
    platform?: string;
    text: string;
}
export interface SeriesCreate {
    synopsis?: string;
    title: string;
}
export interface SessionBody {
    space_id?: string | null;
    title?: string;
}
export interface Settings {
    ads_on_free?: boolean | null;
    ads_on_paid?: boolean | null;
    house_ads?: boolean | null;
}
/**
 * ``POST /api/v1/jobs/{job_id}/share`` — the created (or existing) link.
 */
export interface ShareCreateResponse {
    data: ShareLinkModel;
    message?: string | null;
    status?: number;
}
/**
 * Owner-facing share link (data of ``ShareCreateResponse``).
 *
 * ``token`` is the unguessable 128-bit public handle and ``url`` is the built
 * public share-page link. ``extra="allow"`` future-proofs the owner view (it is
 * scoped to the reel's owner, so exposing ``job_id`` / ``view_count`` here is
 * safe — this model is NEVER used for the unauthenticated public page).
 */
export interface ShareLinkModel {
    created_at?: string | null;
    job_id?: string;
    revoked?: boolean;
    token: string;
    url: string;
    view_count?: number;
    [key: string]: unknown;
}
/**
 * SAFE public share-page DTO (unauthenticated read).
 *
 * STRICT by design — it deliberately does NOT set ``extra="allow"`` so any
 * field beyond this safe allowlist is dropped by pydantic, guaranteeing the
 * clean ``result_key``, the owning ``user_id`` and every private financial
 * (credits, cost, revenue, even ``view_count``) can never leak to a public
 * viewer. Mirrors ``app.services.share.SAFE_PUBLIC_FIELDS`` exactly.
 */
export interface SharePublicModel {
    created_at?: string | null;
    sharer_referral_code?: string;
    title?: string;
    watermarked_preview_url?: string;
}
/**
 * ``GET /api/v1/public/r/{token}`` — the safe public share page (no auth).
 */
export interface SharePublicResponse {
    data: SharePublicModel;
    message?: string | null;
    status?: number;
}
/**
 * ``DELETE /api/v1/me/shares/{token}`` — revoke result.
 */
export interface ShareRevokeResponse {
    data?: unknown;
    message?: string | null;
    status?: number;
}
export interface ShopifyBody {
    limit?: number;
    shop: string;
    token: string;
}
export interface ShotBody {
    aspect?: "9:16" | "16:9" | "1:1";
    first_frame_url?: string;
    product: string;
    seconds?: number;
}
export interface ShotPromptBody {
    action: string;
    scene?: string;
    shot_index?: number;
}
export interface SignIn {
    access_token: string;
    device?: string;
}
export interface SkillBody {
    instructions: string;
    name: string;
}
export interface SlotBody {
    id: string;
    scheduled_at: string;
    source: string;
}
/**
 * The generated post metadata: a ready-to-copy title, caption and hashtags.
 *
 * ``hashtags`` is a list of individual tags (each already ``#``-prefixed by the
 * generator) the creator can paste when posting; it may be empty when the model
 * returns none. ``title`` / ``caption`` may be edited before posting.
 */
export interface SocialMetadata {
    caption?: string;
    hashtags?: Array<string>;
    title?: string;
    [key: string]: unknown;
}
/**
 * Supported social-platform catalog; ``data`` is a list of ``{id, name}``.
 *
 * Defaults to ``[]`` so an empty/degraded catalog still validates against the
 * shared falsy-dropping ``get_response`` envelope.
 */
export interface SocialPlatformsResponse {
    data?: Array<{
        [key: string]: unknown;
    }>;
    message?: string | null;
    status?: number;
}
/**
 * Request body for ``POST /api/v1/jobs/{job_id}/social``.
 *
 * ``platform`` selects the target social network the copy is tailored for and
 * MUST be one of ``tiktok`` / ``instagram`` / ``youtube_shorts`` (validated at
 * handler time — a 400 otherwise). ``language`` is optional: when omitted the
 * caption is generated in the *job's own* configured language, so a bare
 * ``{"platform": "tiktok"}`` body works. The subject/script the copy is built
 * from are always derived server-side from the job's persisted data, never from
 * client input, so no free-text prompt is accepted here.
 */
export interface SocialRequest {
    language?: string | null;
    platform: string;
}
/**
 * ``POST /api/v1/jobs/{job_id}/social`` — generated post copy for a platform.
 */
export interface SocialResponse {
    data: SocialMetadata;
    message?: string | null;
    status?: number;
}
export interface SoundBody {
    room_tone?: boolean;
    sfx?: boolean;
}
export interface SourceInfo {
    avoid_terms?: Array<string>;
    duration_s: number;
    height: number;
    language?: string;
    platform: string;
    source_ref: string;
    url: string;
    width: number;
}
/**
 * One source row expanded into a narration script by the runner.
 */
export interface SourceItemIn {
    body?: string;
    title?: string;
    url?: string;
}
export interface SpaceBody {
    name?: string;
    website_url?: string;
}
/**
 * Request body for ``POST /api/v1/generation/speak/generate``.
 *
 * * ``image_key`` (required) — an R2 key the caller OWNS (validated
 *   server-side, never an arbitrary URL): the reference face/photo.
 * * ``audio_key`` (required) — an R2 key the caller OWNS: the driving narration.
 * * ``provider`` — optional reviewed lipsync provider key (e.g. ``"musetalk"``);
 *   empty resolves a commercial-safe default deterministically.
 */
export interface SpeakGenerateRequest {
    audio_key: string;
    image_key: string;
    provider?: string | null;
}
/**
 * One speak generation's lifecycle snapshot (a ``Job(kind='speak_lipsync')``).
 *
 * ``generation_id`` is the underlying job id — pollable via
 * ``GET /api/v1/generation/speak/generations/{id}``. ``state`` follows the shared
 * job states; ``talking_video_key`` is the rendered clip's R2 key once complete
 * (empty until then).
 */
export interface SpeakGeneration {
    correlation_id?: string;
    error?: string;
    generation_id: string;
    license_class?: string;
    progress?: number;
    provider?: string;
    result_url?: string;
    retry_eligible?: boolean;
    state?: number;
    talking_video_key?: string;
    [key: string]: unknown;
}
/**
 * Canonical speak create/poll response envelope.
 */
export interface SpeakGenerationResponse {
    data: SpeakGeneration;
    message?: string | null;
    status?: number;
}
/**
 * ``GET /generation/speak/providers`` — bounded lipsync selectors + licenses.
 */
export interface SpeakProvidersResponse {
    data?: {
        [key: string]: unknown;
    };
    message?: string | null;
    status?: number;
}
export interface SpendPolicyUpdate {
    byok_allowed?: boolean | null;
    monthly_budget_micros?: number | null;
    spend_min_role?: string | null;
}
export interface Stars {
    stars: number;
}
export interface StartRenderBody {
    backend: string;
    label?: string;
    max_cost_micros: number;
    spec?: {
        [key: string]: unknown;
    };
    workflow_version?: string;
    workspace_id?: string | null;
}
export interface StartTestBody {
    mode?: "publish" | "manual";
    platforms?: Array<string>;
    variant_ids?: Array<string>;
}
export interface StatusBody {
    reply_text?: string;
    status: string;
}
export interface StepStatusBody {
    note?: string;
    product_name: string;
    status: string;
    step_key: string;
}
export interface StoreRedeemRequest {
    platform?: string | null;
    product_id: string;
    purchased_at?: string | null;
    transaction_id: string;
}
export interface StreamBody {
    action_id?: string | null;
    choice?: "yes" | "no" | "connect" | "retry" | "skip" | "approve" | "reject" | "use_product" | "recheck" | null;
    edits?: {
        [key: string]: unknown;
    } | null;
    step?: string;
    text?: string | null;
    value?: string | null;
}
export interface StreamCreate {
    access_tier?: string;
    title: string;
}
export interface StyleHooksRequest {
    description?: string;
    features?: Array<string>;
    formats?: Array<string>;
    language?: string;
    style?: string;
    title: string;
}
export interface SubmitBody {
    clip_url: string;
}
/**
 * ``POST /api/v1/me/workspaces/{id}/subscribe`` body — start a recurring checkout.
 *
 * ``plan_key`` selects the self-serve plan (``starter`` | ``pro``; Free is the
 * implicit base and Enterprise is sales-led). ``interval`` (``month`` | ``year``)
 * picks the plan's recurring price for that cadence, ``seats`` (1..plan limit)
 * is recorded on the subscription, and ``provider`` is ``stripe`` | ``creem`` |
 * ``polar``. No subscription/credit grant happens on this request — the
 * verified webhook fulfils it idempotently once the provider confirms payment.
 */
export interface SubscribeRequest {
    interval?: string;
    plan_key: string;
    provider?: string;
    seats?: number;
}
/**
 * ``POST /api/v1/me/workspaces/{id}/subscribe`` — the hosted-checkout envelope.
 */
export interface SubscribeResponse {
    data: SubscriptionCheckoutModel;
    message?: string | null;
    status?: number;
}
/**
 * Hosted-checkout payload returned by ``subscribe`` (Stripe checkout url + refs).
 *
 * Extra provider fields (``reference``, ``credits``) are allowed through for
 * clients that render them. Credits are granted only on webhook confirmation.
 */
export interface SubscriptionCheckoutModel {
    checkout_url: string;
    plan_key?: string;
    provider?: string;
    workspace_id?: string | null;
    [key: string]: unknown;
}
/**
 * A workspace's billing subscription (tenant-scoped, secret-free).
 *
 * ``status`` is one of ``active | past_due | canceled | trialing``; only
 * ``active`` / ``trialing`` grant the plan's entitlements (a lapsed subscription
 * falls back to the base/free plan). ``provider_ref`` is the provider-side id
 * (e.g. the Stripe subscription id) — never a secret.
 */
export interface SubscriptionModel {
    created_at?: string | null;
    current_period_end?: string | null;
    interval?: string;
    plan_key?: string;
    provider?: string;
    provider_ref?: string;
    seats?: number;
    status?: string;
    updated_at?: string | null;
    workspace_id: string;
}
/**
 * ``GET /api/v1/me/workspaces/{id}/subscription`` — the workspace subscription.
 *
 * ``data`` is ``null`` when the workspace has no subscription (it then resolves
 * to the base/free plan entitlements).
 */
export interface SubscriptionResponse {
    data?: SubscriptionModel | null;
    message?: string | null;
    status?: number;
}
export interface SubtitleRequest {
    bgm_file?: string | null;
    bgm_type?: string | null;
    bgm_volume?: number | null;
    font_name?: string | null;
    font_size?: number;
    rounded_subtitle_background?: boolean;
    stroke_color?: string | null;
    stroke_width?: number;
    subtitle_enabled?: string | null;
    subtitle_position?: string | null;
    text_background_color?: boolean | string;
    text_fore_color?: string | null;
    video_language?: string | null;
    video_script: string;
    video_source?: string | null;
    voice_name?: string | null;
    voice_rate?: number | null;
    voice_volume?: number | null;
}
export interface SupportCreditsRequest {
    amount: number;
    reason: string;
    ref: string;
}
export interface SupportRefundRequest {
    reason: string;
}
export interface TakesRequest {
    count?: number;
    delivery?: string;
    engine?: string;
    language?: string;
    line?: string | null;
    place_word: string;
    reply_line?: string;
}
export interface TargetBody {
    target_id: string;
}
export interface TaskResponse {
    data: TaskResponseData;
    message?: string | null;
    status?: number;
}
export interface TaskResponseData {
    task_id: string;
}
export interface TaskVideoRequest {
    bgm_file?: string | null;
    bgm_type?: string | null;
    bgm_volume?: number | null;
    custom_audio_file?: string | null;
    custom_position?: number;
    custom_system_prompt?: string;
    font_name?: string | null;
    font_size?: number;
    match_materials_to_script?: boolean;
    n_threads?: number | null;
    paragraph_number?: number;
    rounded_subtitle_background?: boolean;
    sonilo_bgm_prompt?: string;
    stroke_color?: string | null;
    stroke_width?: number;
    subtitle_enabled?: boolean | null;
    subtitle_position?: string | null;
    text_background_color?: boolean | string;
    text_fore_color?: string | null;
    video_aspect?: VideoAspect | null;
    video_clip_duration?: number;
    video_clip_speed?: number | null;
    video_concat_mode?: VideoConcatMode | null;
    video_count?: number;
    video_language?: string | null;
    video_materials?: Array<MaterialInfo> | null;
    video_music_prompt?: string;
    video_script?: string;
    video_script_prompt?: string;
    video_source?: string | null;
    video_subject: string;
    video_terms?: string | Array<unknown> | null;
    video_transition_mode?: VideoTransitionMode | null;
    voice_name?: string | null;
    voice_rate?: number | null;
    voice_volume?: number | null;
}
export interface TelegramBody {
    bot_token: string;
    chat_id: string;
    label?: string;
    workspace_id?: string | null;
}
export interface TemplateBody {
    name: string;
}
/**
 * Job-template catalog; ``data`` is a list of template descriptors.
 *
 * Defaults to ``[]`` so a degraded read still validates against the shared
 * falsy-dropping ``get_response`` envelope.
 */
export interface TemplateCatalogResponse {
    data?: Array<{
        [key: string]: unknown;
    }>;
    message?: string | null;
    status?: number;
}
export interface TestBody {
    text?: string;
}
/**
 * A time-anchored text overlay over the produced output.
 */
export interface TextOverlayInput {
    end_s: number;
    position?: string;
    start_s: number;
    text: string;
}
/**
 * A multi-segment, caption + overlay export (OpenCut-style EDL).
 */
export interface TimelineExportRequest {
    music?: MusicTrackInput | null;
    overlays?: Array<TextOverlayInput>;
    segments: Array<TimelineSegmentInput>;
}
/**
 * One source trim on the timeline (segments may reuse source ranges).
 */
export interface TimelineSegmentInput {
    caption?: string | null;
    source_in: number;
    source_out: number;
    speed?: number;
}
export interface TitleUpdate {
    access_tier?: string | null;
    available_from?: string | null;
    available_until?: string | null;
    credits?: Array<Credit> | null;
    episode?: number | null;
    genres?: Array<string> | null;
    geo_countries?: Array<string> | null;
    geo_mode?: string | null;
    kind?: string | null;
    position?: number | null;
    rating?: string | null;
    season?: number | null;
    series_id?: string | null;
    synopsis?: string | null;
    title?: string | null;
}
export interface TokenBody {
    name?: string;
    scopes?: Array<string>;
    ttl_days?: number;
    workspace_id?: string | null;
}
export interface TonePreviewBody {
    caption?: string;
    hashtags?: Array<string>;
    platforms: Array<string>;
    title?: string;
    tone?: string;
}
export interface TrackLinkBody {
    url: string;
}
export interface TrainBody {
    rank?: number;
    steps?: number;
    workspace_id?: string;
}
export interface TrainRequest {
    quoted_credits: number;
}
/**
 * One transcript window; ``score`` optional (the ranker fills it in).
 */
export interface TranscriptSegment {
    end_s: number;
    hook?: string;
    reason?: string;
    score?: number | null;
    start_s: number;
    text?: string;
    title?: string;
    [key: string]: unknown;
}
export interface TransferChallengeRequest {
    amount_micros: number;
    recipient_handle: string;
    saved_recipient_id?: string | null;
    source_account_id: string;
}
/**
 * Configure account-keyed send limits; zero disables that policy limit.
 */
export interface TransferPolicyRequest {
    daily_limit_micros: number;
    per_transfer_limit_micros: number;
    source_account_id: string;
}
/**
 * Send Mint-backed AI tokens to a public handle or Mint address.
 */
export interface TransferRequest {
    amount_micros: number;
    challenge_id: string;
    recipient_handle: string;
    source_account_id: string;
}
export interface TrendIn {
    counts?: Array<number>;
    kind?: string;
    label?: string;
    trend_id: string;
}
export interface TurnaroundRequest {
    style?: string;
}
export interface TvApprove {
    user_code: string;
}
export interface TvPoll {
    device_token: string;
}
export interface UnreadCountData {
    unread_count?: number;
}
/**
 * ``GET /api/v1/me/notifications/unread_count`` — cheap bell-badge poll.
 *
 * A dedicated, count-only endpoint so the client can refresh the unread badge
 * on a short interval without materialising any notification rows.
 */
export interface UnreadCountResponse {
    data: UnreadCountData;
    message?: string | null;
    status?: number;
}
export interface UpdateBody {
    canvas?: {
        [key: string]: unknown;
    } | null;
    title?: string | null;
}
export interface UpdateProjectBody {
    angles?: Array<AngleIn> | null;
    title?: string | null;
}
export interface UploadAbort {
    key: string;
    upload_id: string;
}
export interface UploadComplete {
    key: string;
    kind?: string;
    parts: Array<UploadPart>;
    seconds: number;
    short_side: number;
    size_bytes?: number;
    title: string;
    upload_id: string;
}
export interface UploadPart {
    ETag: string;
    PartNumber: number;
}
export interface UploadParts {
    key: string;
    part_numbers: Array<number>;
    upload_id: string;
}
export interface UploadStart {
    content_type: string;
    filename: string;
    seconds?: number | null;
    size_bytes: number;
}
export interface UrlDetectRequest {
    url: string;
}
export interface UrlIngestRequest {
    url: string;
}
/**
 * A workspace's metered usage + overage for a billing month (tenant-scoped).
 *
 * ``usage`` is the per-metric ``{metric: total}`` aggregate for ``period``
 * (``'YYYY-MM'``); ``overage`` details each metric's usage vs its plan limit.
 * Both are strictly scoped to ``workspace_id`` — never another tenant's rows.
 */
export interface UsageModel {
    overage?: Array<MetricOverageModel>;
    period: string;
    usage?: {
        [key: string]: unknown;
    };
    workspace_id: string;
}
/**
 * ``GET /api/v1/me/workspaces/{id}/usage`` — tenant-scoped usage + overage.
 */
export interface UsageResponse {
    data: UsageModel;
    message?: string | null;
    status?: number;
}
export interface UseFaceBody {
    library_item_id: string;
}
export interface ValidationError {
    ctx?: Record<string, unknown>;
    input?: unknown;
    loc: Array<string | number>;
    msg: string;
    type: string;
}
export interface VariantsBody {
    angle_ids: Array<string>;
    aspects: Array<string>;
    avatar_id?: string;
    caption_style?: string;
    formats: Array<string>;
    voice_id?: string;
}
export interface VariationsBody {
    ad_account_id: string;
    entity_id: string;
    media?: "video" | "image";
    space_id?: string | null;
    workspace_id?: string | null;
}
/**
 * ``CloneVoiceRequest`` plus the live-phrase verification fields (M7.2).
 *
 * Optional in the schema so a missing field gets a clear 400 with a ``code``
 * (``voice_verification_required``) instead of a generic 422.
 */
export interface VerifiedCloneVoiceRequest {
    consent: boolean;
    description?: string | null;
    name: string;
    sample_key: string;
    verification_key?: string | null;
    verification_token?: string | null;
}
export interface VerifyBody {
    asset_id: string;
}
export type VideoAspect = "16:9" | "9:16" | "1:1";
export interface VideoBody {
    aspect_ratio?: string;
    brief?: VideoBrief | null;
    duration?: number;
    identity_passport_id?: string;
    identity_version?: number | null;
    image_url?: string;
    model: string;
    prompt?: string;
    references?: Array<VideoReference> | null;
}
/**
 * Structured shot brief; when sent, it replaces the free-text prompt.
 */
export interface VideoBrief {
    action: string;
    audio?: string;
    camera?: string;
    constraints?: string;
    continuity?: string;
    format: string;
}
export type VideoConcatMode = "random" | "sequential";
export interface VideoMaterialRetrieveResponse {
    data?: unknown;
    message?: string | null;
    status?: number;
}
export interface VideoMaterialUploadResponse {
    data?: unknown;
    message?: string | null;
    status?: number;
}
export interface VideoQuoteRequest {
    op?: string;
    source_job_id: string;
}
/**
 * One role-tagged reference image: a public https URL or your own uploaded file key.
 */
export interface VideoReference {
    role: string;
    url: string;
}
export interface VideoRequest {
    op?: string;
    quoted_credits: number;
    source_job_id: string;
}
export interface VideoScriptRequest {
    custom_system_prompt?: string;
    paragraph_number?: number;
    video_language?: string | null;
    video_script_prompt?: string;
    video_subject?: string | null;
}
export interface VideoScriptResponse {
    data?: unknown;
    message?: string | null;
    status?: number;
}
export interface VideoSocialMetadataRequest {
    language?: string | null;
    platform?: string | null;
    video_script?: string | null;
    video_subject?: string | null;
}
export interface VideoSocialMetadataResponse {
    data?: unknown;
    message?: string | null;
    status?: number;
}
export interface VideoTermsRequest {
    amount?: number | null;
    match_materials_to_script?: boolean;
    video_script?: string | null;
    video_subject?: string | null;
}
export interface VideoTermsResponse {
    data?: unknown;
    message?: string | null;
    status?: number;
}
export type VideoTransitionMode = "None" | "Shuffle" | "FadeIn" | "FadeOut" | "SlideIn" | "SlideOut" | "ZoomIn" | "ZoomOut";
export interface VoiceBody {
    delivery?: string;
    engine?: string;
    reply_line?: string;
    take_key?: string;
}
/**
 * Persisted ``UserVoice`` row serialised to the public envelope.
 *
 * ``voice_id`` is the narrator selector (``"elevenlabs:<provider_voice_id>"``),
 * NOT the internal row id (``id``).
 */
export interface VoiceCloneData {
    id: string;
    name: string;
    status?: string;
    voice_id: string;
    [key: string]: unknown;
}
export interface VoiceCloneResponse {
    data: VoiceCloneData;
    message?: string | null;
    status?: number;
}
export interface VoiceDesignBody {
    description?: string;
}
export interface VoiceDesignRequest {
    character: string;
    description?: string;
    product?: string;
}
/**
 * Normalised ElevenLabs voices; ``data`` is a list of dicts.
 */
export interface VoiceListResponse {
    data: Array<{
        [key: string]: unknown;
    }>;
    message?: string | null;
    status?: number;
}
export interface VoiceLockBody {
    generated_voice_id: string;
}
export interface VoiceLockRequest {
    character: string;
    generated_voice_id: string;
    product?: string;
}
export interface WallRequest {
    approved?: boolean;
}
/**
 * ``GET /api/v1/me/workspaces/{id}/webhooks/{sub}/deliveries`` — recent deliveries.
 *
 * ``data`` defaults to ``[]`` (newest first). Tenant-scoped: only the owning
 * workspace's deliveries are ever returned.
 */
export interface WebhookDeliveryListResponse {
    data?: Array<WebhookDeliveryModel>;
    message?: string | null;
    status?: number;
}
/**
 * One delivery attempt-record of an event to a subscription (SECRET-FREE).
 *
 * ``status`` is one of ``pending | delivered | failed``. ``attempts`` /
 * ``last_attempt_at`` / ``response_code`` reflect the capped-backoff retry state.
 * The signed ``payload`` body is intentionally omitted from this summary view;
 * only delivery metadata is exposed.
 */
export interface WebhookDeliveryModel {
    attempts?: number;
    created_at?: string | null;
    event_id: string;
    event_type: string;
    id: string;
    last_attempt_at?: string | null;
    response_code?: number | null;
    status?: string;
    subscription_id: string;
}
/**
 * ``POST /api/v1/me/workspaces/{id}/webhooks/{sub}/test`` — the test delivery record.
 */
export interface WebhookDeliveryResponse {
    data: WebhookDeliveryModel;
    message?: string | null;
    status?: number;
}
/**
 * ``POST /api/v1/me/workspaces/{id}/webhooks`` body — register a subscription.
 *
 * ``url`` is the customer callback endpoint; it is validated through the SAME
 * SSRF guard the delivery primitive uses BEFORE any row is persisted, so a
 * loopback / private / link-local / metadata target is refused (``400``) and a
 * customer can never register an internal URL to SSRF the platform. ``event_types``
 * must be a non-empty subset of :data:`WEBHOOK_EVENT_TYPES`. The signing secret is
 * minted server-side (never client-supplied) and revealed exactly once in the
 * response.
 */
export interface WebhookSubscribeRequest {
    event_types: Array<string>;
    url: string;
}
/**
 * The ONE-TIME reveal returned by ``POST .../webhooks``.
 *
 * SECURITY: ``secret`` is the subscription's HMAC signing key and is present
 * **only here, exactly once**, at creation. The server persists it only as a
 * Fernet blob, so the plaintext is **unrecoverable** afterwards — a lost secret
 * means the subscription must be deleted and re-created. Every subsequent
 * list/get response uses the secret-free :class:`WebhookSubscriptionModel`.
 */
export interface WebhookSubscriptionCreatedModel {
    created_at?: string | null;
    enabled?: boolean;
    event_types?: Array<string>;
    id: string;
    secret: string;
    updated_at?: string | null;
    url: string;
    workspace_id: string;
}
/**
 * ``POST /api/v1/me/workspaces/{id}/webhooks`` — the one-time subscription reveal.
 */
export interface WebhookSubscriptionCreatedResponse {
    data: WebhookSubscriptionCreatedModel;
    message?: string | null;
    status?: number;
}
/**
 * ``GET /api/v1/me/workspaces/{id}/webhooks`` — the workspace's subscriptions.
 *
 * ``data`` defaults to ``[]`` (the shared envelope drops a falsy payload) so a
 * workspace with no subscriptions still validates. The signing secret is never
 * included on any row.
 */
export interface WebhookSubscriptionListResponse {
    data?: Array<WebhookSubscriptionModel>;
    message?: string | null;
    status?: number;
}
/**
 * A webhook subscription serialised to its public, SECRET-FREE envelope.
 *
 * NEVER carries the signing secret (plaintext OR the encrypted blob) — only the
 * id, owning ``workspace_id``, callback ``url``, subscribed ``event_types``, the
 * ``enabled`` kill-switch, and lifecycle timestamps. The plaintext signing secret
 * is only ever available once, at create time (see
 * :class:`WebhookSubscriptionCreatedModel`).
 */
export interface WebhookSubscriptionModel {
    created_at?: string | null;
    enabled?: boolean;
    event_types?: Array<string>;
    id: string;
    updated_at?: string | null;
    url: string;
    workspace_id: string;
}
/**
 * One ranked hook with its deterministic, aggregated win score.
 */
export interface WinningHookModel {
    avg_retention_pct?: number;
    engagements?: number;
    hook: string;
    reels?: number;
    views?: number;
    win_score?: number;
    [key: string]: unknown;
}
/**
 * ``GET /api/v1/me/winning-hooks`` — the caller's top hooks by win score.
 *
 * ``data`` defaults to ``[]`` (a creator with no logged outcomes has no
 * winners) because the shared envelope drops a falsy payload.
 */
export interface WinningHooksResponse {
    data?: Array<WinningHookModel>;
    message?: string | null;
    status?: number;
}
/**
 * One ranked template with its deterministic, aggregated win score.
 */
export interface WinningTemplateModel {
    avg_retention_pct?: number;
    engagements?: number;
    reels?: number;
    template: string;
    views?: number;
    win_score?: number;
    [key: string]: unknown;
}
/**
 * ``GET /api/v1/me/winning-templates`` — the caller's top templates by win score.
 *
 * ``data`` defaults to ``[]`` (a creator with no logged outcomes has no
 * winners) because the shared envelope drops a falsy payload.
 */
export interface WinningTemplatesResponse {
    data?: Array<WinningTemplateModel>;
    message?: string | null;
    status?: number;
}
export interface WordIn {
    end: number;
    start: number;
    text: string;
}
export interface WorkflowBody {
    graph?: {
        [key: string]: unknown;
    } | null;
    name?: string;
    space_id?: string | null;
}
/**
 * Request body for ``POST /api/v1/workspaces``.
 *
 * ``name`` is intentionally left unconstrained (beyond a length cap) so that an
 * empty/whitespace-only value is rejected by the service with a clean HTTP 400
 * (mapped from ``ValueError``) rather than a schema-level HTTP 422 — keeping the
 * "missing/invalid workspace name" contract in one place (the service).
 */
export interface WorkspaceCreateRequest {
    name: string;
}
/**
 * Envelope for a workspace shared-pool credit read / grant.
 *
 * ``data`` carries ``{"balance": <int>}`` — the workspace's current shared
 * pool balance (``SUM(delta)`` over its ledger rows). Returned by both
 * ``GET /api/v1/workspaces/{id}/credits`` and, after a successful grant,
 * ``POST /api/v1/workspaces/{id}/credits/grant``.
 */
export interface WorkspaceCreditsResponse {
    data?: unknown;
    message?: string | null;
    status?: number;
}
/**
 * Request body for ``POST /api/v1/workspaces/{id}/credits/grant``.
 *
 * ``amount`` is the number of credits to add to the workspace's SHARED pool.
 * It is intentionally left unconstrained at the schema level (beyond being an
 * ``int``) so a non-positive value is rejected by the repository with a clean
 * HTTP 400 (mapped from ``ValueError``) rather than a schema-level HTTP 422 —
 * keeping the "invalid grant amount" contract in one place. ``reason`` is an
 * optional free-text audit label recorded on the ledger row.
 *
 * Note: this is the manual/admin grant path (dev + top-ups). Real purchases
 * flow through Stripe in a later phase; this endpoint is the ADMIN-only escape
 * hatch for seeding a pool.
 */
export interface WorkspaceGrantRequest {
    amount: number;
    reason?: string | null;
}
/**
 * Envelope for workspace reads/writes.
 *
 * ``data`` carries either a single workspace descriptor (create) or a list of
 * them (``GET /api/v1/me/workspaces``); each descriptor includes the caller's
 * own ``role`` in that workspace. Typed as ``Any`` so the one model serves both
 * the single- and list-shaped payloads under the shared ``get_response``
 * envelope.
 */
export interface WorkspaceResponse {
    data?: unknown;
    message?: string | null;
    status?: number;
}
export interface app__controllers__v1__ads__AccountBody {
    account_id: string;
    currency?: string;
    identity_id?: string;
    identity_name?: string;
}
export interface app__controllers__v1__ads__CallbackBody {
    code: string;
    state: string;
}
export interface app__controllers__v1__adstudio__CreateProjectBody {
    angle_count?: number;
    angles?: Array<AngleIn> | null;
    image_keys?: Array<string>;
    language?: string | null;
    product?: ManualProduct | null;
    title?: string;
    url?: string | null;
    use_llm?: boolean;
}
export interface app__domains__adclone__router__PlanRequest {
    aspect?: "9:16" | "16:9";
    brief: CloneBrief;
    engine?: string | null;
    language?: string;
    product?: string;
    set_key?: string;
    variations?: number;
}
export interface app__domains__ads__allocator__routes__DecisionBody {
    decision: string;
    note?: string;
    split?: {
        [key: string]: number;
    } | null;
}
export interface app__domains__ads__allocator__routes__ProposeBody {
    manual_networks?: Array<ManualNetworkBody> | null;
    total_daily_minor?: number | null;
}
export interface app__domains__adstudio__publish_router__RemakeBody {
    accept_low_confidence?: boolean;
}
export interface app__domains__approvals__router__DecisionBody {
    edits?: {
        [key: string]: unknown;
    } | null;
    note?: string;
    via?: string;
}
export interface app__domains__approvals__router__SettingsBody {
    auto_sources?: {
        [key: string]: boolean;
    };
}
export interface app__domains__apps_shelf__router__RunRequest {
    inputs: Inputs;
    quoted_credits: number;
}
export interface app__domains__capture__router__CreateBody {
    cursor?: boolean;
    duration_s?: number | null;
    formats?: Array<string>;
    kind?: "auto" | "website" | "native_game" | "app_store" | "play_store";
    native?: NativeBody | null;
    url?: string;
}
export interface app__domains__clipmarket__router__CampaignBody {
    budget_micros: number;
    cpm_micros: number;
    min_views?: number;
    title?: string;
}
export interface app__domains__competitors__router__BrandBody {
    countries?: Array<string>;
    meta_page_ids?: Array<string>;
    name: string;
    search_terms?: string;
    space_id?: string | null;
    tiktok_advertiser_ids?: Array<string>;
}
export interface app__domains__content_month__router__DecisionBody {
    decision: string;
}
export interface app__domains__content_month__router__PlanBody {
    count?: number;
    url: string;
}
export interface app__domains__design__router__CreateBody {
    brand_kit_id?: string | null;
    canvas?: {
        [key: string]: unknown;
    } | null;
    prompt?: string;
    size_preset?: string;
    template?: string;
    template_id?: string | null;
    title?: string;
}
export interface app__domains__design__router__ImageBody {
    data: string;
}
export interface app__domains__design__router__ScheduleBody {
    caption?: string;
    channel_ids?: Array<string>;
    platforms: Array<string>;
    scheduled_at?: string | null;
}
export interface app__domains__film__router__CreateProjectBody {
    beats?: Array<BeatIn>;
    character: CharacterIn;
    target_runtime_s?: number | null;
    title?: string;
    total_shots?: number;
}
export interface app__domains__film__story8__PlanRequest {
    character_id?: string | null;
    language?: string;
    script?: string;
    topic?: string;
}
export interface app__domains__film__story8__StartRequest {
    character_id?: string | null;
    language?: string;
    lines: Array<string>;
    mode?: string;
    quoted: QuotedCredits;
}
export interface app__domains__film__very_time__BrandBody {
    chest_text?: string;
    cta?: string;
    garment?: string;
    garment_ref?: string;
    logo_ref?: string;
    preset?: string;
}
export interface app__domains__film__very_time__PlanRequest {
    brand?: app__domains__film__very_time__BrandBody | null;
    character_id?: string | null;
    duration_s?: number;
    language?: string;
    line?: string | null;
    look?: string;
    payoff?: string;
    place_word: string;
    ritual: string;
    sound?: SoundBody | null;
    voice?: VoiceBody | null;
}
export interface app__domains__film__very_time__StartRequest {
    brand?: app__domains__film__very_time__BrandBody | null;
    character_id?: string | null;
    duration_s?: number;
    language?: string;
    line?: string | null;
    look?: string;
    mode?: string;
    payoff?: string;
    place_word: string;
    quoted: QuotedCredits;
    ritual: string;
    sound?: SoundBody | null;
    voice?: VoiceBody | null;
}
export interface app__domains__gallery__router__PublishRequest {
    job_id: string;
    title?: string;
}
export interface app__domains__gateway__media_router__ImageBody {
    model: string;
    prompt: string;
}
export interface app__domains__gateway__router__KeyBody {
    daily_cap_micros?: number;
    label?: string;
    markup_bps?: number;
    min_fee_micros?: number;
}
export interface app__domains__insights__winner_loop_router__RemakeBody {
    accept_low_confidence?: boolean;
}
export interface app__domains__integrations__router__CallbackBody {
    code: string;
    state: string;
}
export interface app__domains__integrations__router__DecisionBody {
    note?: string;
}
export interface app__domains__integrations__router__KeyBody {
    api_key: string;
}
export interface app__domains__integrations__router__ProposeBody {
    ad_account_id?: string | null;
    days?: number;
}
export interface app__domains__lipsync_translate__router__PlanBody {
    actor_id: string;
    captions?: boolean;
    engine?: "kling" | "infinitetalk";
    seconds: number;
    source_language?: string;
    targets: Array<string>;
    transcript?: string;
    video_url: string;
}
export interface app__domains__multipost__router__AccountBody {
    daily_cap?: number | null;
    min_gap_minutes?: number | null;
    paused?: boolean | null;
    posting_hours?: Array<number> | null;
    timezone?: string | null;
}
export interface app__domains__multipost__router__CallbackBody {
    code: string;
    state: string;
}
export interface app__domains__multipost__router__CampaignBody {
    account_ids: Array<string>;
    allow_comments?: boolean;
    allow_duet?: boolean;
    allow_stitch?: boolean;
    brand_content?: boolean;
    brand_organic?: boolean;
    caption?: string;
    consent?: boolean;
    hashtags?: Array<string>;
    job_ids: Array<string>;
    mode?: string;
    name?: string;
    start_at?: string | null;
    tiktok_mode?: string;
    visibility: string;
}
export interface app__domains__presets_hub__router__PlanRequest {
    brand_kit_id?: string | null;
    character_id?: string | null;
    image_key?: string | null;
    subject: string;
}
export interface app__domains__presets_hub__router__RunRequest {
    job_id: string;
    opened_at: string;
}
export interface app__domains__publishing__extended__router__CallbackBody {
    code: string;
    state: string;
}
export interface app__domains__social_inbox__autopilot_router__SettingsBody {
    auto_like?: boolean | null;
    blocked_words?: Array<string> | null;
    daily_cap?: number | null;
    enabled?: boolean | null;
    hide_abuse?: boolean | null;
    hide_spam?: boolean | null;
    reply_mode?: string | null;
    reply_to_questions?: boolean | null;
    route_leads?: boolean | null;
}
/**
 * Start a wallet top-up checkout (launch-gated).
 */
export interface app__domains__wallet__schemas__CheckoutRequest {
    amount_usd: string;
    provider?: "creem" | "stripe";
    workspace_id?: string | null;
}
export interface app__domains__workflows__router__ScheduleBody {
    enabled?: boolean;
    hour?: number;
    weekday?: number | null;
}
/**
 * Request body for ``POST /api/v1/billing/checkout``.
 *
 * ``provider`` selects the payment rail (Stripe globally, iyzico for TR local
 * cards, Creem and Polar as merchant-of-record checkout platforms); ``plan_key``
 * selects the credit pack (``"starter"`` | ``"pro"`` — the free plan is a signup
 * grant, not a purchase).
 *
 * ``workspace_id`` is optional: when present the caller is buying the pack for
 * a workspace's SHARED credit pool rather than their personal balance. The API
 * layer requires the caller to be an ``admin`` (or higher) of that workspace
 * before a checkout session is created, and the id is threaded into the provider
 * session metadata so the webhook funds the pool (supported on Stripe, Creem and
 * Polar). ``None``/empty means a personal purchase (unchanged behaviour).
 */
export interface app__models__schema__CheckoutRequest {
    plan_key: string;
    provider: string;
    workspace_id?: string | null;
}
/**
 * Request body for ``POST /api/v1/jobs/{job_id}/publish`` (Phase 3).
 *
 * Re-publishes a *completed* job's rendered output to social platforms.
 * ``platforms`` selects the targets (e.g. ``["tiktok", "instagram"]``);
 * ``youtube_privacy_status`` overrides the YouTube visibility when publishing
 * to YouTube.
 */
export interface app__models__schema__PublishRequest {
    platforms?: Array<string>;
    youtube_privacy_status?: string | null;
}
