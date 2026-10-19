export declare const JobState: {
    readonly Failed: -1;
    readonly Complete: 1;
    readonly Processing: 4;
};
export type JobStateValue = number;
export type KnownJobState = (typeof JobState)[keyof typeof JobState];
export declare function isTerminalJobState(state: JobStateValue): boolean;
export declare function isFailedJobState(state: JobStateValue): boolean;
export type GenerationPhase = "queued" | "running" | "completed" | "failed";
export declare function generationPhase(state: JobStateValue, progress: number): GenerationPhase;
