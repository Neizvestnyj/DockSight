import { z } from 'zod';
import { containerSchema } from './contracts';

const cursor = z.string().min(1).max(1024).nullable();
const chatMatch = z
  .strictObject({
    turn_id: z.string().uuid(),
    excerpt: z.string().min(1).max(1024),
    start: z.number().int().min(0),
    end: z.number().int().positive(),
  })
  .refine(({ excerpt, start, end }) => start < end && end <= excerpt.length);
const chatResult = z.strictObject({
  id: z.string().uuid(),
  host: z.string().min(1).max(128),
  title: z.string().max(240),
  updated_at: z.iso.datetime({ offset: true }),
  match: chatMatch.nullable(),
});
const containerResult = z.strictObject({
  id: z.string().regex(/^[a-f0-9]{64}$/),
  name: z.string().min(1).max(2048),
  image: z.string().max(2048),
  state: containerSchema.shape.state,
  compose_project: z.string().max(2048).nullable(),
  swarm_stack: z.string().max(2048).nullable(),
});
export const chatSearchPageSchema = z.strictObject({ items: z.array(chatResult).max(50), next_cursor: cursor });
export const containerSearchPageSchema = z.strictObject({
  items: z.array(containerResult).max(50),
  next_cursor: cursor,
});

export type ChatSearchResult = z.infer<typeof chatResult>;
export type ContainerSearchResult = z.infer<typeof containerResult>;
export interface SearchPage<Row> {
  items: Row[];
  next_cursor: string | null;
}
