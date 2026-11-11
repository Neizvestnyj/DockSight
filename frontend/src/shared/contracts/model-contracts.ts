import { z } from 'zod';

export const providerIdSchema = z.enum(['ollama', 'openai', 'anthropic', 'gemini', 'compatible']);
export const modelSelectionSchema = z.strictObject({
  provider: providerIdSchema,
  model: z.string().min(1).max(256),
});
export const modelProvidersSchema = z.strictObject({
  schema_version: z.literal(1),
  default: modelSelectionSchema,
  providers: z
    .array(
      z.strictObject({
        id: providerIdSchema,
        name: z.string().min(1).max(64),
        configured: z.boolean(),
        default_model: z.string().min(1).max(256).nullable(),
      }),
    )
    .max(5)
    .refine((rows) => new Set(rows.map((row) => row.id)).size === rows.length),
});
export const modelCatalogSchema = z.strictObject({
  schema_version: z.literal(1),
  provider: providerIdSchema,
  models: z.array(z.strictObject({ id: z.string().min(1).max(256) })).max(2000),
  state: z.enum(['ready', 'stale', 'unavailable']),
  code: z.string().min(1).max(64),
  checked_at: z.iso.datetime({ offset: true }).nullable(),
  refreshing: z.boolean(),
});

export type ProviderId = z.infer<typeof providerIdSchema>;
export type ModelSelection = z.infer<typeof modelSelectionSchema>;
export type ModelProviders = z.infer<typeof modelProvidersSchema>;
export type ModelCatalog = z.infer<typeof modelCatalogSchema>;

export const providerNames: Record<ProviderId, string> = {
  ollama: 'Ollama',
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  gemini: 'Gemini',
  compatible: 'OpenAI-compatible',
};
