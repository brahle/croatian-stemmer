#!/usr/bin/env bash
# Build (and optionally push) the labeling app image for linux/amd64:
#
#   ${REGISTRY}/labeling:v<version>
#
# <version> is [project].version in pyproject.toml. Never `latest`.
#
#   ./build.sh                                   build and load locally as
#                                                croatian-stemmer/labeling:v<version>
#   REGISTRY=registry.example.com/team ./build.sh --push
#                                                build and push, then print the pushed digest
#
# --push requires REGISTRY; there is no default registry. After pushing, bump the image tag in
# your deployment config to v<version>. build.sh does not edit Git. Bump the version before
# building a changed image: an existing tag is refused rather than overwritten.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

PLATFORM="${PLATFORM:-linux/amd64}"
VERSION="$(sed -n 's/^version = "\(.*\)"$/\1/p' pyproject.toml | head -n 1)"
TAG="v${VERSION}"

PUSH=false
for arg in "$@"; do
  case "$arg" in
    --push) PUSH=true ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

if $PUSH && [[ -z "${REGISTRY:-}" ]]; then
  echo "Set REGISTRY to the registry/namespace to push to, e.g. REGISTRY=registry.example.com/team" >&2
  exit 2
fi
REGISTRY="${REGISTRY:-croatian-stemmer}"
REGISTRY="${REGISTRY%/}"
IMAGE="${REGISTRY}/labeling:${TAG}"

[[ "$TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "version '$VERSION' in pyproject.toml is not X.Y.Z" >&2; exit 2; }
if [[ -n $(git status --porcelain --untracked-files=normal) ]]; then
  echo "Commit changes before creating a release image." >&2
  exit 1
fi
command -v docker >/dev/null || { echo "docker not found" >&2; exit 2; }

if $PUSH; then
  if docker buildx imagetools inspect "$IMAGE" >/dev/null 2>&1; then
    echo "$IMAGE already exists; bump the version in pyproject.toml." >&2
    exit 1
  fi
  docker buildx build --platform "$PLATFORM" --file Dockerfile.web \
    --label "org.opencontainers.image.revision=$(git rev-parse HEAD)" --tag "$IMAGE" --push .
  digest="$(docker buildx imagetools inspect "$IMAGE" --format '{{json .Manifest.Digest}}' | tr -d '"')"
  echo "pushed ${IMAGE}"
  echo "digest ${IMAGE%:*}@${digest}"
  echo "Next: bump the image tag in your deployment config to ${TAG}."
else
  docker buildx build --platform "$PLATFORM" --file Dockerfile.web \
    --label "org.opencontainers.image.revision=$(git rev-parse HEAD)" --tag "$IMAGE" --load .
  echo "built ${IMAGE} $(docker image inspect "$IMAGE" --format '{{.Id}}')"
fi
