// What the window asks of the daemon about images, and the HTTP client for it.
// Mock mode (mock-images.ts) implements the same interface. An image goes up as
// the whole request body; every route needs the token, so the window fetches
// an image's bytes itself and never points an <img> at the route.

import type { Api } from "./api";
import { asImageLimits, asStoredImage, isImageId } from "./image-guards";
import type { ImageLimits, StoredImage } from "./image-types";
import { ok, refused, type Result } from "./settings-api";

export interface ImagesApi {
  limits(): Promise<Result<ImageLimits>>;
  /** Stores an image to send with a message; a refusal is one plain sentence. */
  upload(file: Blob): Promise<Result<StoredImage>>;
  /** The image's bytes, or null when it was removed or never existed. */
  get(id: string): Promise<Result<Blob | null>>;
  /** Forgets an image that was uploaded and then taken out before sending. */
  remove(id: string): Promise<Result<true>>;
}

const SHAPE = "The answer was not in the expected shape.";
const imagePath = (id: string): string => `/api/images/${id}`;

export class HttpImages implements ImagesApi {
  constructor(private readonly api: Api) {}

  async limits(): Promise<Result<ImageLimits>> {
    const answer = await this.api.call("GET", "/api/images/limits");
    if (!answer.ok) return answer;
    const limits = asImageLimits(answer.value);
    return limits ? ok(limits) : refused(SHAPE);
  }

  async upload(file: Blob): Promise<Result<StoredImage>> {
    const answer = await this.api.upload("/api/images", "image", file);
    if (!answer.ok) return answer;
    const image = asStoredImage(answer.value);
    return image ? ok(image) : refused(SHAPE);
  }

  get(id: string): Promise<Result<Blob | null>> {
    // An id that is not one could only miss; it never reaches a URL.
    if (!isImageId(id)) return Promise.resolve(ok(null));
    return this.api.blob(imagePath(id));
  }

  async remove(id: string): Promise<Result<true>> {
    if (!isImageId(id)) return refused("That is not an image's name.");
    const answer = await this.api.call("DELETE", imagePath(id));
    return answer.ok ? ok(true) : answer;
  }
}
