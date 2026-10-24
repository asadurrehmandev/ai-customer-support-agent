import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getArticle, getArticles, searchKb, type Article, type ArticleDetail, type Hit } from "../api.ts";

export function Knowledge() {
  const { id } = useParams();
  const [articles, setArticles] = useState<Article[] | null>(null);
  const [error, setError] = useState("");
  const [article, setArticle] = useState<ArticleDetail | null>(null);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<Hit[] | null>(null);
  const [band, setBand] = useState("");
  const [searchError, setSearchError] = useState("");

  useEffect(() => {
    getArticles()
      .then(setArticles)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Could not load articles."));
  }, []);

  useEffect(() => {
    if (!id) {
      setArticle(null);
      return;
    }
    getArticle(id)
      .then(setArticle)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Could not load that article."));
  }, [id]);

  return (
    <div className="grid h-full min-h-0 grid-cols-1 lg:grid-cols-[300px_minmax(0,1fr)]">
      <section className={`${id ? "hidden lg:block" : "block"} min-h-0 overflow-auto border-r border-line`}>
        <header className="px-4 py-3">
          <h1 className="text-lg font-bold">Knowledge</h1>
          <p className="text-sm text-muted">{articles ? `${articles.length} articles` : "Loading"}</p>
        </header>
        {error ? <p className="px-4 text-sm text-danger">{error}</p> : null}
        <ul>
          {(articles || []).map((row) => (
            <li key={row.id}>
              <Link to={`/knowledge/${row.id}`} className={`block border-t border-line px-4 py-3 no-underline ${id === row.id ? "bg-yellow text-[#141816]" : "text-ink"}`}>
                <span className="font-bold">{row.title}</span>
                <span className="mt-1 block text-xs uppercase">{sourceLabel(row.source_type)}</span>
              </Link>
            </li>
          ))}
        </ul>
      </section>
      <section className="min-h-0 overflow-auto px-4 py-4 pb-24">
        <form
          className="flex flex-col gap-2 sm:flex-row"
          onSubmit={(event) => {
            event.preventDefault();
            setSearchError("");
            searchKb(query)
              .then((result) => {
                setHits(result.hits);
                setBand(result.band);
              })
              .catch((err: unknown) => setSearchError(err instanceof Error ? err.message : "Search failed."));
          }}
        >
          <label className="sr-only" htmlFor="kb-q">
            Search the help center
          </label>
          <input
            id="kb-q"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Try a customer question"
            className="w-full rounded-lg border border-line bg-sheet px-3 py-2 text-sm"
          />
          <button type="submit" className="rounded-lg bg-yellow px-3 py-2 text-sm font-bold text-[#141816]">
            Search
          </button>
        </form>
        {searchError ? <p className="mt-2 text-sm text-danger">{searchError}</p> : null}
        {hits ? (
          <div className="mt-4">
            <p className="text-sm text-muted">Gate: {band}. Scores are the retriever's, not a confidence percentage.</p>
            <ul className="mt-2 space-y-3">
              {hits.map((hit) => (
                <li key={`${hit.article_id}-${hit.section}`} className="rounded-xl border border-line p-3">
                  <p className="font-bold">
                    {hit.title} § {hit.section}
                  </p>
                  <p className="text-xs tabular-nums text-muted">
                    cosine {hit.cosine} · bm25 {hit.bm25} · rerank {hit.rerank}
                    {hit.gate ? ` · ${hit.gate}` : ""}
                  </p>
                  <p className="mt-2 text-sm leading-6">{hit.text}</p>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {id ? (
          <Link to="/knowledge" className="mt-4 inline-block text-sm underline lg:hidden">
            All articles
          </Link>
        ) : null}
        {article ? (
          <article className="mt-6 max-w-3xl">
            <p className="text-xs uppercase text-muted">{sourceLabel(article.source_type)} · {article.source_name}</p>
            <h2 className="mt-1 text-2xl font-bold">{article.title}</h2>
            {article.sections.map((section) => (
              <section key={`${section.section}-${section.text.slice(0, 24)}`} className="mt-5">
                <h3 className="font-bold">{section.section}</h3>
                <p className="mt-1 text-sm leading-6">{section.text}</p>
              </section>
            ))}
          </article>
        ) : (
          <p className="mt-6 max-w-xl text-sm text-muted">Pick an article, or search. Answers in chat are quoted from these sections and cite the title and heading.</p>
        )}
        <Upload onDone={() => getArticles().then(setArticles)} />
      </section>
    </div>
  );
}

function Upload({ onDone }: { onDone: () => void }) {
  const [message, setMessage] = useState("");
  return (
    <form
      className="mt-8 border-t border-line pt-4"
      onSubmit={async (event) => {
        event.preventDefault();
        const form = event.currentTarget;
        const input = form.elements.namedItem("file") as HTMLInputElement;
        const file = input.files?.[0];
        if (!file) return;
        const body = new FormData();
        body.append("file", file);
        setMessage("Uploading");
        const response = await fetch("/api/kb/documents", { method: "POST", body });
        if (!response.ok) {
          setMessage("Upload failed. Use Markdown, HTML, or PDF under 2MB.");
          return;
        }
        const saved = await response.json();
        setMessage(`Ingested ${saved.title}.`);
        form.reset();
        onDone();
      }}
    >
      <label className="text-sm font-bold" htmlFor="kb-file">
        Add a Markdown, HTML, or PDF article
      </label>
      <div className="mt-2 flex flex-col gap-2 sm:flex-row sm:items-center">
        <input id="kb-file" name="file" type="file" accept=".md,.markdown,.html,.htm,.pdf" className="text-sm" />
        <button type="submit" className="rounded-lg border border-line px-3 py-2 text-sm">
          Ingest
        </button>
      </div>
      {message ? <p className="mt-2 text-sm text-muted">{message}</p> : null}
    </form>
  );
}

function sourceLabel(kind: string) {
  if (kind === "md") return "Markdown";
  if (kind === "html") return "HTML";
  if (kind === "pdf") return "PDF";
  return kind;
}
