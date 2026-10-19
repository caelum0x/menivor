#!/bin/zsh
# encode_web.sh <key> [hero]: master -> web loop (muted), poster, full (with sound)
set -e
key=$1
S=${SHOWCASE_OUT:-$(git rev-parse --show-toplevel)/public-samples-staging}
M=$S/masters/$key.mp4
mkdir -p $S/web $S/full
dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 $M)
len=$(python3 -c "print(min(9.0, float('$dur')))")
if [[ "$2" == "hero" ]]; then size=720:1280; rate=1300k; else size=540:960; rate=1100k; fi
ffmpeg -v error -y -t $len -i $M -an -vf "scale=${size}:flags=lanczos,fps=30" \
  -c:v libx264 -preset slow -crf 23 -maxrate $rate -bufsize 2600k -profile:v high -pix_fmt yuv420p \
  -g 60 -movflags +faststart $S/web/$key.mp4
ffmpeg -v error -y -ss 0.5 -i $M -vf "scale=540:960:flags=lanczos" -frames:v 1 -q:v 5 $S/web/$key-poster.jpg
ffmpeg -v error -y -i $M -vf "scale=720:1280:flags=lanczos" -c:v libx264 -preset slow -crf 25 \
  -profile:v high -pix_fmt yuv420p -c:a aac -b:a 96k -movflags +faststart $S/full/$key-full.mp4
ls -la $S/web/$key.mp4 $S/web/$key-poster.jpg $S/full/$key-full.mp4 | awk '{print $5, $9}'
