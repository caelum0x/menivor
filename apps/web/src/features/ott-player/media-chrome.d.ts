import type * as React from "react";

type El = React.DetailedHTMLProps<React.HTMLAttributes<HTMLElement>, HTMLElement> & { class?: string; slot?: string };

declare module "react" {
  namespace JSX {
    interface IntrinsicElements {
      "media-controller": El;
      "media-control-bar": El;
      "media-play-button": El;
      "media-mute-button": El;
      "media-time-range": El;
      "media-time-display": El & { showduration?: boolean | string };
      "media-fullscreen-button": El;
      "media-pip-button": El;
      "media-airplay-button": El;
    }
  }
}
