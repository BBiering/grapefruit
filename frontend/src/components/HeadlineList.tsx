import type { Article } from "../types";

export default function HeadlineList({ articles }: { articles: Article[] }) {
  if (articles.length === 0) {
    return <div className="muted">no headlines in window</div>;
  }
  return (
    <ul style={{ paddingLeft: "1.2rem" }}>
      {articles.map((a, i) => (
        <li key={i} style={{ marginBottom: "0.4rem" }}>
          <a href={a.url} target="_blank" rel="noreferrer">
            {a.headline}
          </a>
          <div className="muted">
            {a.source} {a.ts ? `— ${a.ts.split("T")[0]}` : ""}
          </div>
        </li>
      ))}
    </ul>
  );
}
