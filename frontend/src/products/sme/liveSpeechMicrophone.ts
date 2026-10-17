/**
 * Echo cancellation stays on because the expert is played from the speakers.
 * Browser noise suppression stays off: OpenAI near_field is the noise filter
 * on the audio we send, and a second suppressor muffles speech before it arrives.
 */
export const liveSpeechMicrophone = {
  channelCount: 1,
  echoCancellation: true,
  noiseSuppression: false,
  autoGainControl: true,
} as const
