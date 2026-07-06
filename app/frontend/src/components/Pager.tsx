/**
 * Prev/Page/Next footer for a server-paginated table, paired with `usePagination`.
 * `shown` is the row count on the current page; `testId` prefixes the data-testids
 * (`{testId}-pager`, `{testId}-prev`, `{testId}-next`) so each screen keeps its hooks.
 */
export function Pager({
  page,
  pageSize,
  count,
  shown,
  hasNext,
  onPrev,
  onNext,
  testId,
}: {
  page: number;
  pageSize: number;
  count: number;
  shown: number;
  hasNext: boolean;
  onPrev: () => void;
  onNext: () => void;
  testId?: string;
}) {
  const start = (page - 1) * pageSize + 1;
  const end = (page - 1) * pageSize + shown;
  return (
    <div className="pager" data-testid={testId ? `${testId}-pager` : undefined}>
      <span className="pager-info">
        Showing {start}–{end} of {count}
      </span>
      <div className="spacer" />
      <button
        className="btn btn-sm"
        disabled={page <= 1}
        onClick={onPrev}
        data-testid={testId ? `${testId}-prev` : undefined}
      >
        Prev
      </button>
      <span className="pager-page">Page {page}</span>
      <button
        className="btn btn-sm"
        disabled={!hasNext}
        onClick={onNext}
        data-testid={testId ? `${testId}-next` : undefined}
      >
        Next
      </button>
    </div>
  );
}
