export const JobState = {
    Failed: -1,
    Complete: 1,
    Processing: 4,
};
export function isTerminalJobState(state) {
    return state === JobState.Complete || state === JobState.Failed;
}
export function isFailedJobState(state) {
    return state === JobState.Failed;
}
export function generationPhase(state, progress) {
    if (state === JobState.Complete)
        return "completed";
    if (state === JobState.Failed)
        return "failed";
    return progress > 0 ? "running" : "queued";
}
