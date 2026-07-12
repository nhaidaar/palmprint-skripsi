type MediaPipeVisionModule = any

const VISION_BUNDLE_URL = '/static/vendor/mediapipe/vision_bundle.mjs'
const WASM_URL = '/static/vendor/mediapipe/wasm'
const HAND_LANDMARKER_TASK_URL = '/static/vendor/mediapipe/hand_landmarker.task'

export async function createHandLandmarker() {
  const moduleUrl = new URL(VISION_BUNDLE_URL, window.location.href).href
  const mediapipe = (await import(/* @vite-ignore */ moduleUrl)) as MediaPipeVisionModule
  const vision = await mediapipe.FilesetResolver.forVisionTasks(WASM_URL)
  const handLandmarker = await mediapipe.HandLandmarker.createFromOptions(vision, {
    baseOptions: { modelAssetPath: HAND_LANDMARKER_TASK_URL },
    runningMode: 'VIDEO',
    numHands: 1,
  })
  return { handLandmarker, DrawingUtils: mediapipe.DrawingUtils }
}
