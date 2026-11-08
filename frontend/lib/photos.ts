/**
 * Phone photos of pages are often 4–12 MB each and stored sideways with an EXIF
 * "rotate me" flag. Before upload we redraw each photo upright (the browser applies
 * the EXIF orientation) and shrink it to a size that is still sharp enough to read.
 * This keeps uploads small and fast and the pages straight for OCR.
 */

const MAX_SIDE = 2200; // px on the long side: plenty for OCR of a book page
const QUALITY = 0.85;
const SKIP_BELOW = 600 * 1024; // already-small images are sent as they are

function canvasToJpeg(canvas: HTMLCanvasElement): Promise<Blob | null> {
  return new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", QUALITY));
}

async function prepareOne(file: File): Promise<File> {
  if (file.size < SKIP_BELOW && file.type !== "image/webp") return file;
  let bitmap: ImageBitmap;
  try {
    bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
  } catch {
    return file; // the browser cannot decode it: let the server decide
  }
  try {
    const scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(bitmap.width * scale));
    canvas.height = Math.max(1, Math.round(bitmap.height * scale));
    const ctx = canvas.getContext("2d");
    if (!ctx) return file;
    ctx.fillStyle = "#fff"; // transparent PNG areas become white, not black
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    const blob = await canvasToJpeg(canvas);
    if (!blob || (blob.size >= file.size && scale === 1 && file.type === "image/jpeg")) return file;
    const name = file.name.replace(/\.[^.]+$/, "") + ".jpg";
    return new File([blob], name, { type: "image/jpeg", lastModified: file.lastModified });
  } finally {
    bitmap.close();
  }
}

/** Upright, shrunk copies of the photos, in the same order. Calls onProgress(done, total). */
export async function preparePhotos(files: File[], onProgress: (done: number, total: number) => void = () => {}): Promise<File[]> {
  const out: File[] = [];
  for (const [i, f] of files.entries()) {
    out.push(await prepareOne(f)); // one at a time: big photos use a lot of memory
    onProgress(i + 1, files.length);
  }
  return out;
}

export function isImageFile(f: File): boolean {
  return /^image\/(jpeg|png|webp)$/.test(f.type) || /\.(jpe?g|png|webp)$/i.test(f.name);
}
