export type Memory = { total_bytes: number; available_bytes: number; used_bytes: number }
export type Gpu = { id: string; index?: number; name: string; memory: Memory | null; error: string | null; unified_memory?: boolean }
export type Host = {
  instance_id: string
  host: { hostname: string; os: string; label: string; role: string; scope: string }
  ram: Memory | null; ram_error: string | null; gpus: Gpu[]; gpu_error: string | null
  observed_at: string | null; sequence: number; age_seconds: number | null
  stale: boolean; stale_after_seconds: number; status: string; loading_enabled: boolean
  loading_reason: string
  /** Display only: RAM and per-GPU VRAM held by each running model's processes, keyed by model ID, then GPU ID. */
  model_memory?: Record<string, ModelMemory>
}
export type ModelMemory = { ram_bytes: number | null; gpus: Record<string, number>; error: string | null }
export type Snapshot = { data: Host; arrivedAt: number }
export type Model = { id: string; name: string; workload: string; state: string; loading_enabled: boolean; loading_reason?: string | null }
export type RefusalResource = { resource: string; required_bytes: number; available_bytes: number; headroom_bytes?: number }
export type Refusal = { code: string; message: string; resources?: RefusalResource[] }
export type SettingValue = string | number | boolean | null
export type Launch = { preset: string; settings: Record<string, SettingValue>; gpus: number[] }
export type Operation = { id: string; model_id: string; action: string; status: string; simulation: boolean; worker_type: string; created_at?: string; updated_at?: string; error_code?: string | null; error_message?: string | null; refusal?: Refusal | null; launch?: Launch | null }
export type RuntimeSetting = { key: string; label: string; kind: 'int' | 'bool' | 'choice' | 'optional_int'; minimum: number | null; maximum: number | null; unit: string | null; help: string; default: SettingValue; options: string[] | null; option_labels?: Record<string, string>; advanced?: boolean }
/** A published quality score, charted against other models measured the same way. */
export type RuntimeQuality = { metric: string; score: number; estimated: boolean; source?: string | null; as_of?: string | null; note?: string | null }
/** A model that is not run here, with published scores, drawn as reference bars beside the local models. */
export type ReferenceModel = { name: string; workload: string; scores: RuntimeQuality[] }
export type RuntimePreset = { license?: RuntimeLicense | null; quality?: RuntimeQuality | null; rankings?: RuntimeQuality[]; name: string; description?: string | null; gpus: number[]; allowed_gpus: { index: number; name: string }[]; settings: RuntimeSetting[]; estimate: { ram_gib: number; gpu_min_free_gib: Record<string, number> }
  /** GPUs one start may use (overrides the runtime's), and a note per card choice ("0", "1", "0,1") on how the model behaves there. */
  max_gpus?: number | null; card_notes?: Record<string, string> }
export type InputField = { key: string; label: string; kind: 'text' | 'textarea' | 'int' | 'choice' | 'seed' | 'files' | 'crop'; required: boolean; default: string | number | null; minimum: number | null; maximum: number | null; max_length: number | null; options: string[]; placeholder: string | null; help: string; advanced: boolean; accept?: ('image' | 'video' | 'audio' | 'transcript')[]; max_count?: number | null; target?: string | null; shape_field?: string | null; show_when?: Record<string, string>; option_labels?: Record<string, string>; ratio_partner?: string | null; ratio_role?: 'width' | 'height' | null; guide?: string[] }
/** A way of making something, shown as a tab with its own form. */
export type GenerationMode = { key: string; label: string; help: string; inputs: InputField[]; output_kind?: 'audio' | 'image' | 'video' | 'document' }
/** A file uploaded for a request, before a job uses it. */
export type UploadRecord = { id: string; name: string; kind: 'image' | 'video' | 'audio'; mime: string; bytes: number }
/** A job's own copy of a file it was given (a reference picture, video or audio). */
export type JobFile = { name: string; kind: string; mime: string; original: string }
/** A measured time for one result; the first whose conditions all match applies. */
export type Timing = { seconds: number; first_seconds: number | null; when: Record<string, string>; preset: string | null; gpu: number | null; note: string | null }
/** Cues written into the text of a speech request, such as [whispers] or (laugh). */
export type SpeechCues = { open: string; close: string; kind: 'emotion' | 'sounds'; open_vocabulary: boolean; examples: string[]; text: string }
/** What a speech model can do: its voice sources (each served by one of its modes), how it takes direction, and which field plays which role in each mode. */
export type SpeechInfo = {
  voices: Record<string, string>; scene: string | null
  direction: { text: string; examples: string[]; style_fields: Record<string, string>; cues: SpeechCues | null }
  roles: Record<string, Record<string, string>>
}
/** What a picture model can do: its guidance, the tabs that make a picture from words and that edit pictures, and which field plays which role on each tab. */
export type ImageInfo = { guidance: string; create: string | null; edit: string | null; roles: Record<string, Record<string, string>> }
export type MusicInfo = { guidance: string; create: string; cover: string | null; repaint: string | null; roles: Record<string, Record<string, string>> }
export type VideoInfo = { guidance: string; sound: 'none' | 'automatic' | 'prompted'; create: string; picture: string | null; references: string | null; extend: string | null; seconds: Record<string, number>; roles: Record<string, Record<string, string>> }
export type TranscribeInfo = { guidance: string; times: 'none' | 'lines'; speakers: 'none' | 'turns'; checked_minutes: number; roles: Record<string, Record<string, string>> }
export type Generation = { output_kind: 'audio' | 'image' | 'video' | 'document'; inputs: InputField[]; modes?: GenerationMode[]; timings?: Timing[]; make_label?: string | null; result_noun?: string | null; speech?: SpeechInfo | null; image?: ImageInfo | null; music?: MusicInfo | null; video?: VideoInfo | null; transcribe?: TranscribeInfo | null }
/** What a model may be used for: free for company use, free with limits to check, or personal/non-commercial/territory-limited. */
export type RuntimeLicense = { use: 'work' | 'conditions' | 'personal'; weights: string; code?: string | null; note?: string | null; url?: string | null }
export type Runtime = { id: string; kind: string; name: string; description?: string | null; workload: string; port: number; /** Where the model's own server listens: this computer only, or every interface. */ bind?: string; default_preset: string; presets: Record<string, RuntimePreset>; last_launch: Launch | null; max_gpus?: number | null; generation?: Generation | null; license?: RuntimeLicense | null; quality?: RuntimeQuality | null; rankings?: RuntimeQuality[]; chat?: boolean; /** The help assistant runs on this model. */ assistant?: boolean; /** Thinking levels the chat may ask for where the model last started (lowest first). */ thinking?: Thinking | null }
export type Thinking = { levels: string[]; default: string | null; off: boolean }
export type JobOutput = { name: string; mime: string; bytes: number }
/** `details` is what the worker actually used (seed, steps, size, full prompt) and `seconds` taken; `launch` the model settings it ran with. */
export type Job = { id: string; model_id: string; inputs: Record<string, string | number | JobFile[]>; status: 'queued' | 'running' | 'done' | 'failed' | 'cancelled'; progress: string | null; outputs: JobOutput[]; error_message: string | null; created_at: string; finished_at: string | null; details?: Record<string, unknown> | null; launch?: Launch | null }
export type Connection = 'idle' | 'connecting' | 'connected' | 'reconnecting' | 'error'
export type ApiErrorBody = { detail?: string | Refusal; [key: string]: unknown }

export class ApiError extends Error {
  constructor(readonly status: number, readonly body: ApiErrorBody) {
    super(typeof body.detail === 'string' ? body.detail : body.detail?.message ?? `Host request failed (${status}).`)
  }
}
/** What a start with the chosen preset, GPUs and settings would ask admission for (display only). */
export type RuntimeEstimate = {
  ram_bytes: number; gpu_vram_bytes_by_id: Record<string, number>
  ram_headroom_bytes: number; gpu_headroom_bytes: number
  reserved_ram_bytes: number; reserved_gpu_vram_bytes_by_id: Record<string, number>
}
/** A conversation with a text model; `busy` while an answer is being written. */
/** `kind` is 'assistant' for the help bubble's thread, else 'chat'. */
export type Conversation = { id: string; title: string; model_id: string; kind?: 'chat' | 'assistant'; created_at: string; updated_at: string; busy: boolean }
/** Something attached to a chat message: a result from the library (`job_id`), or a file from the person's computer (`file_id`). */
export type ChatAttachment = { job_id?: string; file_id?: string; name: string; mime?: string | null; model_id?: string; kind?: string; bytes?: number }
export type ToolCall = { id: string; name: string; arguments: string }
/** One saved message. A "tool" message is the outcome of one tool call: `job_id` names the job it started. */
export type ChatMessage = {
  id: string; position: number; role: 'user' | 'assistant' | 'tool'; content: string; reasoning: string | null
  attachments: ChatAttachment[]; tool_calls: ToolCall[]; tool_call_id: string | null; job_id: string | null
  /** A tool result's one line for the chat (the model reads the full content). */
  note?: string | null
  status: 'done' | 'stopped' | 'error'; error_message: string | null; created_at: string
}
/** A model server's log: one per start, with that start's model and outcome. */
export type LogEntry = {
  name: string; bytes: number; kind: string; modified_at: string; operation_id: string
  model_id: string | null; action: string | null; status: string | null; error_code: string | null
  error_message: string | null; started_at: string | null
}
export type LogText = { name: string; bytes: number; lines: string[]; truncated: boolean }
/** Settings kept on the host; `searxng_source` says where the search address came from. */
export type HostSettings = { searxng_url: string; searxng_source: 'settings' | 'environment' | 'none' }
export type SearchTestResult = { ok: boolean; message: string }

/** A voice saved in the host's library: a name, its sample (fetched on use) and the words the sample says. */
export type Voice = { id: string; name: string; sample_text: string; mime: string; bytes: number }
