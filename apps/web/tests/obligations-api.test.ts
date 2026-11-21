import { afterEach, expect, it, vi } from "vitest";
import { getObligationReviews, getObligations } from "../lib/api";

vi.mock("next/headers", () => ({ cookies: async () => new Map() }));

afterEach(() => vi.unstubAllGlobals());

it("loads all obligations for a version within the API page limit", async () => {
  const page = Array.from({ length: 200 }, (_, id) => ({ id }));
  const fetch = vi.fn()
    .mockResolvedValueOnce(Response.json(page))
    .mockResolvedValueOnce(Response.json([{ id: 200 }]));
  vi.stubGlobal("fetch", fetch);

  expect((await getObligations("version")).data).toEqual([...page, { id: 200 }]);
  expect(fetch.mock.calls.map(([url]) => new URL(url).search)).toEqual([
    "?limit=200&version_id=version&offset=0",
    "?limit=200&version_id=version&offset=200",
  ]);
});

it("reports a later page failure without returning a partial count", async () => {
  vi.stubGlobal("fetch", vi.fn()
    .mockResolvedValueOnce(Response.json(Array(200).fill({})))
    .mockResolvedValueOnce(new Response(null, { status: 422 })));

  expect(await getObligations()).toEqual({ data: null, error: "API request failed (422)" });
});

it("loads review candidates beyond the first page", async () => {
  const page = Array.from({ length: 200 }, (_, id) => ({ id }));
  const fetch = vi.fn()
    .mockResolvedValueOnce(Response.json({ items: page, total: 201 }))
    .mockResolvedValueOnce(Response.json({ items: [{ id: 200 }], total: 201 }));
  vi.stubGlobal("fetch", fetch);

  expect((await getObligationReviews()).data).toEqual([...page, { id: 200 }]);
  expect(fetch.mock.calls[1]?.[0]).toContain("limit=200&offset=200");
});
