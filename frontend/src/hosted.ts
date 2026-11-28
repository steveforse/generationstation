import type { HostedProvider, Runtime } from './types'

/** Thinking levels the chat offers on a hosted model: a level is sent as the gateway's reasoning effort, off sends none. */
const THINKING = { levels: ['low', 'medium', 'high'], default: 'low', off: true }

/** The models of hosted providers that the chat offers, as chat runtimes with the id "<provider>:<model>". They are always ready:
 * nothing runs on the host for them. */
export function hostedRuntimes(providers: HostedProvider[] | undefined): Runtime[] {
  return (providers ?? []).flatMap((provider) => provider.models.filter((model) => model.enabled).map((model): Runtime => ({
    id: `${provider.id}:${model.id}`, kind: 'hosted', name: `${model.name} (${provider.name})`, description: `Hosted by ${provider.name}.`, workload: 'text',
    port: 0, default_preset: '', presets: {}, last_launch: null, chat: true, thinking: THINKING,
  })))
}
