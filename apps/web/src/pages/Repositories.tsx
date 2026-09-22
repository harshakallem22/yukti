import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { relativeTime } from "../lib/format";
import { Button, Empty, ErrorNote, Field, Panel, Spinner, inputClass } from "../components/ui";

export function Repositories() {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [path, setPath] = useState("");

  const repositories = useQuery({ queryKey: ["repositories"], queryFn: api.listRepositories });
  const create = useMutation({
    mutationFn: api.createRepository,
    onSuccess: () => {
      setName("");
      setPath("");
      queryClient.invalidateQueries({ queryKey: ["repositories"] });
    },
  });

  return (
    <>
      <header className="mb-5">
        <h1 className="text-lg font-semibold">Repositories</h1>
        <p className="text-[13px] text-[var(--color-muted)]">
          Registered repositories. Runs operate on a disposable clone — the source is never
          modified.
        </p>
      </header>

      <Panel title="Register a repository" className="mb-5">
        <form
          className="grid gap-3 sm:grid-cols-[1fr_2fr_auto] sm:items-end"
          onSubmit={(event) => {
            event.preventDefault();
            create.mutate({ name, source_path: path });
          }}
        >
          <Field label="Name">
            <input
              className={inputClass}
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="users-api"
              required
            />
          </Field>
          <Field label="Absolute path" hint="Must be a directory on this machine">
            <input
              className={inputClass}
              value={path}
              onChange={(event) => setPath(event.target.value)}
              placeholder="/path/to/benchmarks/fastapi_bug_001/repo"
              required
            />
          </Field>
          <Button type="submit" variant="primary" disabled={create.isPending}>
            {create.isPending ? "Registering…" : "Register"}
          </Button>
        </form>
        {create.error && (
          <div className="mt-3">
            <ErrorNote error={create.error} />
          </div>
        )}
      </Panel>

      {repositories.isLoading && <Spinner />}
      {repositories.error && <ErrorNote error={repositories.error} />}

      {repositories.data &&
        (repositories.data.length === 0 ? (
          <Empty
            title="No repositories registered."
            hint="Point Yukti at one of the benchmark repositories to get started."
          />
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            {repositories.data.map((repository) => (
              <Panel key={repository.id} title={repository.name}>
                <dl className="space-y-1.5 text-[12px]">
                  <Row label="Path" value={<span className="mono">{repository.source_path}</span>} />
                  <Row label="Language" value={repository.language} />
                  <Row label="Test framework" value={repository.test_framework || "none detected"} />
                  <Row label="Files" value={String(repository.file_count)} />
                  <Row label="Registered" value={relativeTime(repository.created_at)} />
                </dl>
                <div className="mt-3 flex gap-2">
                  <Link to={`/runs/new?repository=${repository.id}`}>
                    <Button variant="primary">Start investigation</Button>
                  </Link>
                  <Link to={`/runs?repository=${repository.id}`}>
                    <Button>View runs</Button>
                  </Link>
                </div>
              </Panel>
            ))}
          </div>
        ))}
    </>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="shrink-0 text-[var(--color-faint)]">{label}</dt>
      <dd className="min-w-0 truncate text-right text-[var(--color-muted)]">{value}</dd>
    </div>
  );
}
