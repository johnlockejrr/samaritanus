import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, books as fetchBooks, health, search } from "./api.js";
import Highlight from "./Highlight.jsx";

const MODES = [
  { id: "lemma", label: "Root" },
  { id: "exact", label: "Exact" },
  { id: "prefix", label: "Prefix" },
  { id: "substr", label: "Contains" },
];

const ORDERS = [
  { id: "canonical", label: "Pentateuch order" },
  { id: "relevance", label: "Relevance" },
];

const PAGE_SIZES = [10, 20, 50];

function readParams() {
  const params = new URLSearchParams(window.location.search);
  const mode = MODES.some((item) => item.id === params.get("mode"))
    ? params.get("mode")
    : "lemma";
  const order = params.get("order") === "relevance" ? "relevance" : "canonical";
  const size = PAGE_SIZES.includes(Number(params.get("size")))
    ? Number(params.get("size"))
    : 10;
  const page = Math.max(1, Number(params.get("page")) || 1);
  return {
    q: params.get("q") || "",
    mode,
    order,
    page,
    size,
    book: params.get("book") || "",
    strongs: params.get("strongs") || "",
  };
}

function writeParams(state) {
  const params = new URLSearchParams();
  if (state.q) params.set("q", state.q);
  if (state.mode && state.mode !== "lemma") params.set("mode", state.mode);
  if (state.order && state.order !== "canonical")
    params.set("order", state.order);
  if (state.page > 1) params.set("page", String(state.page));
  if (state.size !== 10) params.set("size", String(state.size));
  if (state.book) params.set("book", state.book);
  if (state.strongs) params.set("strongs", state.strongs);
  const query = params.toString();
  const next = query
    ? `${window.location.pathname}?${query}`
    : window.location.pathname;
  window.history.replaceState(null, "", next);
}

function Logo() {
  return (
    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-white">
      <svg viewBox="0 0 32 32" className="h-7 w-7" aria-hidden="true">
        <path d="M16 7.5v17" stroke="#1d4ed8" strokeWidth="1.4" />
        <path
          d="M16 9c-1.4-1.1-3.6-1.7-6.4-1.7H7.2v13.2h2.4c2.8 0 5 .6 6.4 1.6"
          fill="none"
          stroke="#1d4ed8"
          strokeWidth="1.6"
          strokeLinejoin="round"
        />
        <path
          d="M16 9c1.4-1.1 3.6-1.7 6.4-1.7h2.4v13.2h-2.4c-2.8 0-5 .6-6.4 1.6"
          fill="none"
          stroke="#1d4ed8"
          strokeWidth="1.6"
          strokeLinejoin="round"
        />
      </svg>
    </span>
  );
}

function Chevron() {
  return (
    <svg
      viewBox="0 0 20 20"
      className="h-4 w-4 text-slate-500 transition-transform group-open:rotate-180"
      aria-hidden="true"
    >
      <path
        d="M5 7.5 10 12.5 15 7.5"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
      />
    </svg>
  );
}

function CountPill({ value }) {
  if (value === undefined || value === null) return null;
  return (
    <span className="ms-auto flex h-7 min-w-7 shrink-0 items-center justify-center rounded-full bg-[#d9e4fb] px-1.5 text-xs font-medium text-blue-800">
      {value}
    </span>
  );
}

function FilterPanel({ title, children }) {
  return (
    <details className="group mb-3 overflow-hidden rounded-xl bg-[#e8eefc]">
      <summary className="flex cursor-pointer list-none items-center justify-between px-4 py-3 text-sm font-semibold text-slate-800">
        {title}
        <Chevron />
      </summary>
      <div className="bg-page/40 px-3 pb-3 pt-1">{children}</div>
    </details>
  );
}

function FilterTree({ children }) {
  return (
    <div className="relative ms-2 border-s border-blue-200/90 ps-3">{children}</div>
  );
}

function MoreList({ items, limit = 6, renderItem }) {
  const [open, setOpen] = useState(false);
  const visible = open ? items : items.slice(0, limit);
  return (
    <div>
      <ul className="space-y-1">{visible.map(renderItem)}</ul>
      {items.length > limit && (
        <button
          type="button"
          className="mt-2 text-xs font-semibold tracking-wide text-blue-700 hover:underline"
          onClick={() => setOpen((value) => !value)}
        >
          {open ? "LESS" : "MORE"}
        </button>
      )}
    </div>
  );
}

function ResultCard({ result }) {
  const reference = `${result.book_name} ${result.chapter}:${result.verse}`;
  return (
    <article
      className="rounded-2xl bg-white px-5 py-5 shadow-sm sm:px-8"
      dir="rtl"
    >
      <h3
        className="mb-2 text-right text-[15px] font-semibold text-blue-700"
        dir="ltr"
      >
        {reference}
      </h3>
      <p
        className="font-hebrew text-right text-[1.45rem] leading-relaxed text-slate-900"
        lang="he"
      >
        <Highlight plain={result.text} matches={result.matches} />
      </p>
    </article>
  );
}

export default function App() {
  const helpRef = useRef(null);
  const [draft, setDraft] = useState(() => readParams().q);
  const [params, setParams] = useState(readParams);
  const [catalog, setCatalog] = useState([]);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [backendDown, setBackendDown] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    Promise.allSettled([
      health(controller.signal),
      fetchBooks(controller.signal),
    ]).then(([healthResult, booksResult]) => {
      if (!active) return;
      if (
        booksResult.status === "fulfilled" &&
        Array.isArray(booksResult.value)
      ) {
        setCatalog(booksResult.value);
      } else {
        setCatalog([]);
      }
      if (healthResult.status === "fulfilled") {
        setBackendDown(healthResult.value?.status !== "ok");
      } else if (booksResult.status === "fulfilled") {
        // Books answered, so the API is up even if health lagged or was stale.
        setBackendDown(false);
      } else if (healthResult.reason?.name !== "AbortError") {
        setBackendDown(true);
      }
    });
    return () => {
      active = false;
      controller.abort();
    };
  }, []);

  useEffect(() => {
    document.title = params.q
      ? `${params.q} · Samaritan Torah Search`
      : "Samaritan Torah Search";
  }, [params.q]);

  useEffect(() => {
    const q = params.q.trim();
    if (!q || params.book === "-") {
      setLoading(false);
      if (!q) setData(null);
      return undefined;
    }
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    search(
      {
        q,
        mode: params.mode,
        order: params.order,
        page: params.page,
        size: params.size,
        book: params.book || undefined,
        strongs:
          params.mode === "lemma" ? params.strongs || undefined : undefined,
      },
      controller.signal,
    )
      .then((body) => {
        setData(body);
        setBackendDown(false);
      })
      .catch((err) => {
        if (err.name === "AbortError") return;
        setData(null);
        setError(
          err instanceof ApiError
            ? err.message
            : "Network error — is the API reachable?",
        );
        if (!(err instanceof ApiError)) setBackendDown(true);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [params]);

  const commit = useCallback((partial, resetPage = true) => {
    setParams((prev) => {
      const next = { ...prev, ...partial };
      if (resetPage && partial.page === undefined) next.page = 1;
      if (partial.q !== undefined && partial.q !== prev.q)
        next.strongs = partial.strongs ?? "";
      if (partial.mode && partial.mode !== "lemma") next.strongs = "";
      writeParams(next);
      return next;
    });
  }, []);

  const onSubmit = (event) => {
    event.preventDefault();
    commit({ q: draft.trim(), strongs: "" });
  };

  const selectedBooks = useMemo(() => {
    if (!params.book || params.book === "-")
      return new Set(params.book === "-" ? [] : catalog.map((b) => b.code));
    return new Set(params.book.split(","));
  }, [params.book, catalog]);

  const toggleBook = (code) => {
    const all = catalog.map((item) => item.code);
    const current =
      params.book && params.book !== "-" ? params.book.split(",") : all;
    const next = current.includes(code)
      ? current.filter((item) => item !== code)
      : [...current, code];
    if (next.length === 0) commit({ book: "-" });
    else if (next.length === all.length) commit({ book: "" });
    else commit({ book: next.join(",") });
  };

  const total = data?.total ?? 0;
  const pageCount = data?.total_pages ?? 0;
  const terms =
    params.mode === "lemma" && Array.isArray(data?.terms) && data.terms.length > 0
      ? data.terms
      : null;
  const lemmas = params.mode === "lemma" ? (data?.lemmas ?? []) : [];
  const forms = params.mode === "lemma" ? (data?.forms ?? []) : [];

  const goToPage = (page) => {
    if (page < 1 || (pageCount && page > pageCount)) return;
    commit({ page }, false);
  };

  return (
    <div className="flex min-h-screen flex-col bg-page text-ink">
      <header className="sticky top-0 z-20 bg-gradient-to-r from-blue-900 to-blue-500 text-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-4 gap-y-3 px-4 py-2.5">
          <div className="flex items-center gap-3">
            <Logo />
            <div className="leading-tight">
              <p className="text-[15px] font-semibold">
                Samaritan Torah Search
              </p>
              <p className="text-xs text-blue-100">Pentateuch</p>
            </div>
          </div>

          <form
            onSubmit={onSubmit}
            className="order-3 w-full sm:order-none sm:min-w-0 sm:flex-1"
            role="search"
          >
            <label htmlFor="q" className="sr-only">
              Search the Samaritan Pentateuch
            </label>
            <div className="flex items-center rounded-full bg-white/95 ps-4 pe-1 shadow-sm">
              <input
                id="q"
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                placeholder="Hebrew word or phrase (vowels OK)"
                dir="auto"
                lang="he"
                maxLength={200}
                className="font-hebrew w-full bg-transparent py-2.5 text-lg text-slate-900 outline-none placeholder:font-sans placeholder:text-base placeholder:text-slate-400"
              />
              <button
                type="submit"
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-blue-800 hover:bg-blue-50"
                aria-label="Search"
              >
                <svg viewBox="0 0 24 24" className="h-5 w-5" aria-hidden="true">
                  <circle
                    cx="11"
                    cy="11"
                    r="6.5"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                  />
                  <path
                    d="M16 16.5 20 20.5"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                  />
                </svg>
              </button>
            </div>
          </form>

          <button
            type="button"
            className="ms-auto text-sm font-medium text-white/95 underline-offset-4 hover:underline"
            onClick={() => helpRef.current?.showModal()}
          >
            How it works
          </button>
        </div>
      </header>

      {backendDown && (
        <div className="bg-red-50 px-4 py-2 text-center text-sm text-red-800">
          The search API is not responding. If you started the UI with{" "}
          <code>npm run dev</code> alone, run <code>./dev.sh</code> instead (it
          starts the API too), then reload.
        </div>
      )}

      <div className="mx-auto grid w-full max-w-6xl flex-1 gap-6 px-4 py-6 lg:grid-cols-[17rem_minmax(0,1fr)]">
        <aside className="lg:pt-1">
          <h2 className="mb-3 text-sm font-semibold tracking-wide text-slate-600">
            Filters
          </h2>

          <FilterPanel title="Meanings">
            {params.mode !== "lemma" && (
              <p className="px-1 py-2 text-sm text-slate-500">
                Meanings are used by Root match.
              </p>
            )}
            {params.mode === "lemma" && !data && (
              <p className="px-1 py-2 text-sm text-slate-500">
                Search a word or phrase to see its lexemes.
              </p>
            )}
            {params.mode === "lemma" && data && lemmas.length === 0 && (
              <p className="px-1 py-2 text-sm text-slate-500">
                No lexicon entry for this spelling.
              </p>
            )}
            {terms && terms.length > 1 && lemmas.length > 0 && (
              <div className="space-y-4 pt-1">
                {terms.map((term) => (
                  <div key={term.word}>
                    <p
                      className="font-hebrew mb-2 px-1 text-base font-semibold text-slate-800"
                      lang="he"
                      dir="rtl"
                    >
                      {term.word}
                    </p>
                    {term.lemmas.length === 0 ? (
                      <p className="px-1 text-sm text-slate-500">
                        No lexicon entry.
                      </p>
                    ) : (
                      <FilterTree>
                        <MoreList
                          items={term.lemmas}
                          renderItem={(lemma) => (
                            <li
                              key={`${term.word}-${lemma.strongs}`}
                              className="flex items-start gap-2 rounded-lg px-1 py-1.5"
                            >
                              <span
                                className="mt-0.5 h-4 w-4 shrink-0 rounded border border-slate-400 bg-white"
                                aria-hidden="true"
                              />
                              <span className="min-w-0 flex-1">
                                <span
                                  className="font-hebrew block text-base leading-tight text-slate-900"
                                  lang="he"
                                  dir="rtl"
                                >
                                  {lemma.display}
                                </span>
                                <span className="mt-0.5 block text-xs text-blue-600/80">
                                  Strong {lemma.strongs.replace(/\s+/g, "")}
                                </span>
                              </span>
                              <CountPill value={lemma.n_occur} />
                            </li>
                          )}
                        />
                      </FilterTree>
                    )}
                  </div>
                ))}
                <p className="px-1 text-xs text-slate-500">
                  Meaning filters apply to single-word searches.
                </p>
              </div>
            )}
            {(!terms || terms.length <= 1) && lemmas.length > 0 && (
              <fieldset className="pt-1">
                <legend className="sr-only">Lexeme</legend>
                <label className="mb-1 flex cursor-pointer items-center gap-2 rounded-lg px-1 py-1.5 text-sm hover:bg-white/60">
                  <input
                    type="radio"
                    name="strongs"
                    className="h-4 w-4 accent-blue-700"
                    checked={!params.strongs}
                    onChange={() => commit({ strongs: "" })}
                  />
                  <span className="font-medium text-slate-800">Select All</span>
                </label>
                <FilterTree>
                  <MoreList
                    items={lemmas}
                    renderItem={(lemma) => (
                      <li key={lemma.strongs}>
                        <label className="flex cursor-pointer items-start gap-2 rounded-lg px-1 py-1.5 hover:bg-white/60">
                          <input
                            type="radio"
                            name="strongs"
                            className="mt-1 h-4 w-4 accent-blue-700"
                            checked={params.strongs === lemma.strongs}
                            onChange={() =>
                              commit({ strongs: lemma.strongs })
                            }
                          />
                          <span className="min-w-0 flex-1">
                            <span
                              className="font-hebrew block text-base leading-tight text-slate-900"
                              lang="he"
                              dir="rtl"
                            >
                              {lemma.display}
                            </span>
                            <span className="mt-0.5 block text-xs text-blue-600/80">
                              Strong {lemma.strongs.replace(/\s+/g, "")}
                            </span>
                          </span>
                          <CountPill value={lemma.n_occur} />
                        </label>
                      </li>
                    )}
                  />
                </FilterTree>
              </fieldset>
            )}
          </FilterPanel>

          <FilterPanel title="Word Forms">
            {params.mode !== "lemma" && (
              <p className="px-1 py-2 text-sm text-slate-500">
                Switch to Root match to list word forms.
              </p>
            )}
            {params.mode === "lemma" && forms.length === 0 && (
              <p className="px-1 py-2 text-sm text-slate-500">
                Word forms appear here after a root search.
              </p>
            )}
            {terms && terms.length > 1 && forms.length > 0 && (
              <div className="space-y-4 pt-1">
                {terms.map((term) => {
                  const rows =
                    term.form_rows?.length > 0
                      ? term.form_rows
                      : (term.forms || []).map((form) => ({ form, n: null }));
                  return (
                    <div key={`forms-${term.word}`}>
                      <p
                        className="font-hebrew mb-2 px-1 text-base font-semibold text-slate-800"
                        lang="he"
                        dir="rtl"
                      >
                        {term.word}
                      </p>
                      {rows.length === 0 ? (
                        <p className="px-1 text-sm text-slate-500">No forms.</p>
                      ) : (
                        <FilterTree>
                          <MoreList
                            items={rows}
                            renderItem={(row) => (
                              <li key={`${term.word}-${row.form}`}>
                                <button
                                  type="button"
                                  className="flex w-full items-center gap-2 rounded-lg px-1 py-1.5 text-left hover:bg-white/60"
                                  onClick={() => {
                                    setDraft(row.form);
                                    commit({
                                      q: row.form,
                                      mode: "exact",
                                      strongs: "",
                                    });
                                  }}
                                >
                                  <span
                                    className="h-4 w-4 shrink-0 rounded border border-slate-400 bg-white"
                                    aria-hidden="true"
                                  />
                                  <span
                                    className="font-hebrew flex-1 text-base text-slate-900"
                                    lang="he"
                                    dir="rtl"
                                  >
                                    {row.form}
                                  </span>
                                  <CountPill value={row.n} />
                                </button>
                              </li>
                            )}
                          />
                        </FilterTree>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
            {(!terms || terms.length <= 1) && forms.length > 0 && (
              <FilterTree>
                <MoreList
                  items={
                    terms?.[0]?.form_rows?.length
                      ? terms[0].form_rows
                      : forms.map((form) => ({ form, n: null }))
                  }
                  renderItem={(row) => (
                    <li key={row.form}>
                      <button
                        type="button"
                        className="flex w-full items-center gap-2 rounded-lg px-1 py-1.5 text-left hover:bg-white/60"
                        onClick={() => {
                          setDraft(row.form);
                          commit({ q: row.form, mode: "exact", strongs: "" });
                        }}
                      >
                        <span
                          className="h-4 w-4 shrink-0 rounded border border-slate-400 bg-white"
                          aria-hidden="true"
                        />
                        <span
                          className="font-hebrew flex-1 text-base text-slate-900"
                          lang="he"
                          dir="rtl"
                        >
                          {row.form}
                        </span>
                        <CountPill value={row.n} />
                      </button>
                    </li>
                  )}
                />
              </FilterTree>
            )}
          </FilterPanel>

          <FilterPanel title="Books">
            <fieldset className="pt-1">
              <legend className="sr-only">Books</legend>
              <label className="mb-1 flex cursor-pointer items-center gap-2 rounded-lg px-1 py-1.5 text-sm hover:bg-white/60">
                <input
                  type="checkbox"
                  className="h-4 w-4 accent-blue-700"
                  checked={
                    catalog.length > 0 &&
                    selectedBooks.size === catalog.length
                  }
                  onChange={() => commit({ book: "" })}
                />
                <span className="font-medium text-slate-800">Select All</span>
              </label>
              <FilterTree>
                {catalog.map((book) => (
                  <label
                    key={book.code}
                    className="flex cursor-pointer items-center gap-2 rounded-lg px-1 py-1.5 text-sm hover:bg-white/60"
                  >
                    <input
                      type="checkbox"
                      className="h-4 w-4 accent-blue-700"
                      checked={selectedBooks.has(book.code)}
                      onChange={() => toggleBook(book.code)}
                    />
                    <span className="flex-1 text-slate-800">
                      {book.book_name}
                    </span>
                    <CountPill value={book.verses} />
                  </label>
                ))}
              </FilterTree>
              {catalog.length === 0 && (
                <p className="px-1 py-2 text-sm text-slate-500">
                  Books load with the index.
                </p>
              )}
            </fieldset>
          </FilterPanel>
        </aside>

        <main>
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-sm font-semibold text-slate-700">
              {params.book === "-"
                ? "No book selected"
                : data
                  ? `${total} ${total === 1 ? "result" : "results"}`
                  : loading
                    ? "Searching…"
                    : "Results"}
            </h2>
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <label className="flex items-center gap-2 rounded-lg border border-blue-200 bg-white px-2 py-1">
                <span className="text-slate-500">Match</span>
                <select
                  value={params.mode}
                  onChange={(event) => commit({ mode: event.target.value })}
                  className="bg-transparent font-medium outline-none"
                  aria-label="Match"
                >
                  {MODES.map((mode) => (
                    <option key={mode.id} value={mode.id}>
                      {mode.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex items-center gap-2 rounded-lg border border-blue-200 bg-white px-2 py-1">
                <span className="text-slate-500">Sort</span>
                <select
                  value={params.order}
                  onChange={(event) => commit({ order: event.target.value })}
                  className="bg-transparent font-medium outline-none"
                  aria-label="Sort"
                >
                  {ORDERS.map((order) => (
                    <option key={order.id} value={order.id}>
                      {order.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </div>

          {error && (
            <div
              role="alert"
              className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
            >
              {error}
            </div>
          )}

          <div
            aria-live="polite"
            className={loading ? "opacity-60" : undefined}
          >
            {!params.q.trim() && !error && (
              <p className="py-16 text-center text-slate-500">
                Search a Hebrew word. Root match finds forms of the same
                Strong's root, including derived nouns.
              </p>
            )}
            {params.book === "-" && (
              <p className="py-16 text-center text-slate-500">
                Select at least one book.
              </p>
            )}
            {data &&
              !loading &&
              params.book !== "-" &&
              data.results.length === 0 && (
                <p className="py-16 text-center text-slate-600">
                  No matches for “{params.q.trim()}”.
                </p>
              )}
            {data && params.book !== "-" && data.results.length > 0 && (
              <div className="space-y-3">
                {data.results.map((result) => (
                  <ResultCard key={result.verse_id} result={result} />
                ))}
              </div>
            )}
          </div>

          {data && pageCount > 1 && params.book !== "-" && (
            <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
              <nav className="flex items-center gap-1" aria-label="Pages">
                <PageButton
                  label="Previous page"
                  disabled={params.page <= 1}
                  onClick={() => goToPage(params.page - 1)}
                >
                  ‹
                </PageButton>
                <PageList
                  page={params.page}
                  pageCount={pageCount}
                  onPage={goToPage}
                />
                <PageButton
                  label="Next page"
                  disabled={params.page >= pageCount}
                  onClick={() => goToPage(params.page + 1)}
                >
                  ›
                </PageButton>
              </nav>
              <label className="flex items-center gap-2 text-sm text-slate-600">
                Items per page
                <select
                  value={params.size}
                  onChange={(event) =>
                    commit({ size: Number(event.target.value) })
                  }
                  className="rounded-md border border-blue-200 bg-white px-2 py-1"
                  aria-label="Items per page"
                >
                  {PAGE_SIZES.map((size) => (
                    <option key={size} value={size}>
                      {size}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          )}
        </main>
      </div>

      <footer className="mt-auto border-t border-blue-200/70 bg-page px-4 py-4">
        <p className="mx-auto max-w-6xl text-center text-xs leading-relaxed text-slate-500">
          Lemma data from the{" "}
          <a
            className="underline"
            href="https://github.com/openscriptures/morphhb"
          >
            Open Scriptures Hebrew Bible
          </a>
          ; root families from{" "}
          <a
            className="underline"
            href="https://github.com/openscriptures/strongs"
          >
            Strong's
          </a>
          . Both under CC BY 4.0. Queries with vowels or cantillation are
          stripped to consonants automatically.
        </p>
      </footer>

      <dialog
        ref={helpRef}
        className="w-[min(36rem,calc(100%-2rem))] rounded-2xl bg-white text-ink shadow-xl"
      >
        <div className="px-6 py-5">
          <div className="mb-3 flex items-start justify-between gap-4">
            <h2 className="text-lg font-semibold">How it works</h2>
            <button
              type="button"
              className="rounded-full px-2 py-1 text-sm text-slate-500 hover:bg-slate-100"
              onClick={() => helpRef.current?.close()}
            >
              Close
            </button>
          </div>
          <div className="space-y-3 text-sm leading-relaxed text-slate-700">
            <p>
              This searches the Samaritan Pentateuch, 5,841 verses, written in
              consonants.
            </p>
            <p>
              <strong>Root</strong> finds forms that share the same Strong's
              root — inflections of the same word, and sole-source derived
              nouns.{" "}
              <span className="font-hebrew" lang="he">
                ברא
              </span>{" "}
              finds{" "}
              <span className="font-hebrew" lang="he">
                ויברא
              </span>
              ,{" "}
              <span className="font-hebrew" lang="he">
                בראם
              </span>
              , and{" "}
              <span className="font-hebrew" lang="he">
                נבראו
              </span>
              .{" "}
              <span className="font-hebrew" lang="he">
                ראש
              </span>{" "}
              finds{" "}
              <span className="font-hebrew" lang="he">
                ראשית
              </span>
              . It does not find lookalikes such as{" "}
              <span className="font-hebrew" lang="he">
                בא
              </span>{" "}
              or{" "}
              <span className="font-hebrew" lang="he">
                ברית
              </span>
              .
            </p>
            <p>
              <strong>Exact</strong> matches the consonants you typed.{" "}
              <strong>Prefix</strong> matches words that start with them.{" "}
              <strong>Contains</strong> matches words that include them. A
              phrase of several words is matched in order.
            </p>
            <p>
              <strong>Pentateuch order</strong> reads Genesis through
              Deuteronomy. <strong>Relevance</strong> puts verses with more
              matching words first.
            </p>
            <p>
              You can paste vocalized or cantillated Hebrew. It is normalized
              (NFKD) and reduced to consonants before searching — the Samaritan
              text itself has no vowel points.
            </p>
          </div>
        </div>
      </dialog>
    </div>
  );
}

function PageButton({ children, label, disabled, onClick }) {
  return (
    <button
      type="button"
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className="h-8 min-w-8 rounded-md px-2 text-slate-600 hover:bg-white disabled:opacity-40"
    >
      {children}
    </button>
  );
}

function PageList({ page, pageCount, onPage }) {
  const maxVisible = 5;
  let start = Math.max(1, page - Math.floor(maxVisible / 2));
  let end = Math.min(pageCount, start + maxVisible - 1);
  if (end - start + 1 < maxVisible) start = Math.max(1, end - maxVisible + 1);
  const items = [];
  if (start > 1) {
    items.push(1);
    if (start > 2) items.push("…");
  }
  for (let i = start; i <= end; i += 1) items.push(i);
  if (end < pageCount) {
    if (end < pageCount - 1) items.push("…");
    items.push(pageCount);
  }
  return items.map((item, index) =>
    item === "…" ? (
      <span key={`gap-${index}`} className="px-1 text-slate-400">
        …
      </span>
    ) : (
      <button
        key={item}
        type="button"
        aria-current={item === page ? "page" : undefined}
        onClick={() => onPage(item)}
        className={`h-8 min-w-8 rounded-md px-2 text-sm ${
          item === page
            ? "bg-blue-600 font-semibold text-white"
            : "text-slate-700 hover:bg-white"
        }`}
      >
        {item}
      </button>
    ),
  );
}
