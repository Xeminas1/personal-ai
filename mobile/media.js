/* Local browser preprocessing. Only normalized images or sampled frames leave
 * the device; this helper does not upload the original video or its audio. */
(() => {
  "use strict";

  const MAX_IMAGE_BYTES = 25_000_000;
  const MAX_VIDEO_BYTES = 250_000_000;
  const MAX_VIDEO_SECONDS = 180;
  const MAX_CONTAINER_BYTES = 5_000_000;
  const MAX_DIMENSION = 1280;
  const EVENT_TIMEOUT_MS = 10_000;

  class MediaPreparationError extends Error {
    constructor(code, message) {
      super(message);
      this.name = "MediaPreparationError";
      this.code = code;
    }
  }

  const fail = (code, message) => new MediaPreparationError(code, message);

  function filename(file, fallback) {
    return String(file.name || fallback).split(/[\\/]/).pop().slice(0, 160);
  }

  function stem(name) {
    return name.replace(/\.[^.]*$/, "").slice(0, 130) || "media";
  }

  function waitFor(element, event, start, errorCode, message) {
    return new Promise((resolve, reject) => {
      let timer;
      const cleanup = () => {
        clearTimeout(timer);
        element.removeEventListener(event, done);
        element.removeEventListener("error", broken);
      };
      const done = () => { cleanup(); resolve(); };
      const broken = () => { cleanup(); reject(fail(errorCode, message)); };
      element.addEventListener(event, done);
      element.addEventListener("error", broken);
      timer = setTimeout(() => {
        cleanup();
        reject(fail("media_timeout", "The browser took too long to read this media. Try a shorter clip or another format."));
      }, EVENT_TIMEOUT_MS);
      try {
        if (start) start();
      } catch {
        broken();
      }
    });
  }

  function encodeFrame(source, width, height, maxBytes) {
    if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0 || width * height > 64_000_000) {
      throw fail("media_dimensions", "This image or video frame has unsupported dimensions. Use a smaller file.");
    }
    const canvas = document.createElement("canvas");
    const context = canvas.getContext("2d", { alpha: false });
    if (!context) throw fail("frame_encoding", "The browser cannot prepare images on this device.");
    let scale = Math.min(1, MAX_DIMENSION / Math.max(width, height));
    try {
      // Reduce quality first, then dimensions, to keep every request bounded.
      for (let resize = 0; resize < 4; resize += 1) {
        canvas.width = Math.max(1, Math.round(width * scale));
        canvas.height = Math.max(1, Math.round(height * scale));
        context.fillStyle = "#ffffff";
        context.fillRect(0, 0, canvas.width, canvas.height);
        context.drawImage(source, 0, 0, canvas.width, canvas.height);
        for (const quality of [0.8, 0.7, 0.6, 0.5]) {
          const encoded = canvas.toDataURL("image/jpeg", quality);
          if (!encoded.startsWith("data:image/jpeg;base64,")) continue;
          const data = encoded.slice(encoded.indexOf(",") + 1);
          const bytes = Math.floor(data.length * 3 / 4) - (data.endsWith("==") ? 2 : data.endsWith("=") ? 1 : 0);
          if (bytes <= maxBytes) return data;
        }
        scale *= 0.75;
      }
      throw fail("frame_encoding", "This image could not be reduced to the supported size. Try a smaller image.");
    } catch (error) {
      if (error instanceof MediaPreparationError) throw error;
      throw fail("frame_encoding", "The browser could not prepare this image or video frame.");
    } finally {
      canvas.width = canvas.height = 1;
    }
  }

  function utf8Base64(value) {
    const bytes = new TextEncoder().encode(value);
    if (bytes.length > MAX_CONTAINER_BYTES) {
      throw fail("too_large", "The sampled video frames exceed the attachment size limit. Try a shorter or smaller clip.");
    }
    const chunks = [];
    for (let offset = 0; offset < bytes.length; offset += 8192) {
      chunks.push(String.fromCharCode(...bytes.subarray(offset, offset + 8192)));
    }
    return btoa(chunks.join(""));
  }

  async function image(file) {
    if (file.size > MAX_IMAGE_BYTES) throw fail("too_large", "Images must be 25 MB or smaller.");
    const url = URL.createObjectURL(file);
    const element = new Image();
    element.decoding = "async";
    try {
      await waitFor(element, "load", () => { element.src = url; }, "image_decode", "The browser could not read this image. Use JPEG, PNG or WebP.");
      const data = encodeFrame(element, element.naturalWidth, element.naturalHeight, 1_000_000);
      return { data, mime: "image/jpeg", name: stem(filename(file, "image")) + ".jpg", visual: { kind: "image", frames: [] } };
    } finally {
      element.removeAttribute("src");
      URL.revokeObjectURL(url);
    }
  }

  async function video(file) {
    if (file.size > MAX_VIDEO_BYTES) throw fail("too_large", "Videos must be 250 MB or smaller.");
    const url = URL.createObjectURL(file);
    const element = document.createElement("video");
    element.preload = "auto";
    element.muted = true;
    element.playsInline = true;
    try {
      await waitFor(element, "loadedmetadata", () => {
        element.src = url;
        element.load();
      }, "video_decode", "The browser could not read this video codec. Try MP4 or WebM supported by your browser.");
      const duration = element.duration;
      if (!Number.isFinite(duration) || duration <= 0 || duration > MAX_VIDEO_SECONDS) {
        throw fail("video_duration", "Videos must have a readable duration and be 3 minutes or shorter.");
      }
      if (element.readyState < 2) {
        await waitFor(element, "loadeddata", null, "video_decode", "The browser could not decode a frame from this video.");
      }
      element.pause();
      const times = [0, duration / 3, duration * 2 / 3, Math.max(duration * 0.95, duration - 0.1)];
      const frames = [];
      for (const time of times) {
        if (Math.abs(element.currentTime - time) > 0.001) {
          await waitFor(element, "seeked", () => { element.currentTime = time; }, "video_decode", "The browser could not seek to a frame in this video.");
        }
        if (element.readyState < 2) {
          await waitFor(element, "loadeddata", null, "video_decode", "The browser could not decode a frame from this video.");
        }
        frames.push({ time: Math.round(element.currentTime * 1000) / 1000, data: encodeFrame(element, element.videoWidth, element.videoHeight, 600_000) });
      }
      const originalName = filename(file, "video");
      const content = { format: "xemai-video-frames-v1", original_name: originalName, duration, frames };
      return {
        data: utf8Base64(JSON.stringify(content)),
        mime: "application/vnd.xemai.video-frames+json",
        name: stem(originalName) + ".xemai-video.json",
        visual: { kind: "video", duration, frames },
      };
    } finally {
      element.pause();
      element.removeAttribute("src");
      element.load();
      URL.revokeObjectURL(url);
    }
  }

  async function prepare(file) {
    if (!file || typeof file.size !== "number" || typeof file.slice !== "function") {
      throw fail("invalid_file", "Choose an image or video file to attach.");
    }
    if (!file.size) throw fail("empty_file", "This media file is empty.");
    const type = String(file.type || "").toLowerCase();
    if (["image/jpeg", "image/png", "image/webp"].includes(type)
        || (!type && /\.(?:jpe?g|png|webp)$/i.test(file.name || ""))) return image(file);
    if (type.startsWith("video/") || (!type && /\.(?:mp4|webm|mov|m4v)$/i.test(file.name || ""))) return video(file);
    throw fail("unsupported_type", "Visual analysis supports JPEG, PNG, WebP and browser-decodable video files.");
  }

  window.XemAiMedia = Object.freeze({ prepare });
})();
