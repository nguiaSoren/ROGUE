"use client";

/**
 * Download buttons for the threat brief. The page already fetched both the
 * markdown and the JSON, so we just turn them into a Blob and download —
 * no API URL, no cross-origin `download`-attribute caveats, works in prod.
 */
function downloadBlob(filename: string, content: string, type: string) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function BriefDownloads({
  date,
  markdown,
  json,
}: {
  date: string;
  markdown: string;
  json: unknown;
}) {
  const btn =
    "px-3 py-1.5 border border-border rounded-md hover:border-rogue-green hover:text-rogue-green transition-colors disabled:opacity-40 disabled:cursor-not-allowed";
  return (
    <div className="flex items-center gap-2 font-mono text-xs">
      <button
        type="button"
        className={btn}
        onClick={() =>
          downloadBlob(`rogue-brief-${date}.md`, markdown, "text/markdown")
        }
      >
        ↓ .md
      </button>
      <button
        type="button"
        className={btn}
        disabled={json == null}
        onClick={() =>
          downloadBlob(
            `rogue-brief-${date}.json`,
            JSON.stringify(json, null, 2),
            "application/json",
          )
        }
      >
        ↓ .json
      </button>
    </div>
  );
}
