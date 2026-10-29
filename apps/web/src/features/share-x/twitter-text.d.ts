declare module "twitter-text" {
  export interface ParsedTweet {
    weightedLength: number;
    valid: boolean;
    permillage: number;
    validRangeStart: number;
    validRangeEnd: number;
    displayRangeStart: number;
    displayRangeEnd: number;
  }

  export interface TwitterTextApi {
    parseTweet(text?: string): ParsedTweet;
    isValidHashtag(hashtag: string): boolean;
  }

  const twitterText: TwitterTextApi;
  export default twitterText;
}
