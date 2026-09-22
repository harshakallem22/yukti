import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { Button, ErrorNote, Field, Panel, Spinner, inputClass } from "../components/ui";

const RISK_MODES = [
  { value: "conservative", label: "Conservative", hint: "Approval needed sooner: 3 files / 100 lines" },
  { value: "standard", label: "Standard", hint: "Balanced: 10 files / 400 lines" },
  { value: "experimental", label: "Experimental", hint: "Wider blast radius: 25 files / 1000 lines" },
];

export function NewRun() {
  const [params] = useSearchParams();
  const navigate = useNavigate();

  const repositories = useQuery({ queryKey: ["repositories"], queryFn: api.listRepositories });
  const [repositoryId, setRepositoryId] = useState(params.get("repository") ?? "");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [repro, setRepro] = useState("");
  const [expected, setExpected] = useState("");
  const [riskMode, setRiskMode] = useState("standard");

  const create = useMutation({
    mutationFn: api.createRun,
    onSuccess: (run) => navigate(`/runs/${run.id}`),
  });

  if (repositories.isLoading) return <Spinner />;

  const selected = repositoryId || repositories.data?.[0]?.id || "";

  return (
    <>
      <header className="mb-5">
        <h1 className="text-lg font-semibold">New agent run</h1>
        <p className="text-[13px] text-[var(--color-muted)]">
          Describe the issue in plain English. Yukti investigates a disposable clone.
        </p>
      </header>

      <Panel>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            create.mutate({
              repository_id: selected,
              issue_title: title,
              issue_body: body,
              repro_steps: repro || undefined,
              expected_behavior: expected || undefined,
              risk_mode: riskMode,
            });
          }}
        >
          <Field label="Repository">
            <select
              className={inputClass}
              value={selected}
              onChange={(event) => setRepositoryId(event.target.value)}
              required
            >
              {repositories.data?.length === 0 && <option value="">No repositories registered</option>}
              {repositories.data?.map((repository) => (
                <option key={repository.id} value={repository.id}>
                  {repository.name} — {repository.source_path}
                </option>
              ))}
            </select>
          </Field>

          <Field label="Issue title">
            <input
              className={inputClass}
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="Duplicate email registration returns 500"
              minLength={3}
              required
            />
          </Field>

          <Field label="Description">
            <textarea
              className={`${inputClass} min-h-28 resize-y`}
              value={body}
              onChange={(event) => setBody(event.target.value)}
              placeholder="When a user registers with an email that already exists, the API returns 500. It should return 409 Conflict."
              minLength={3}
              required
            />
          </Field>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Reproduction steps" hint="Optional">
              <textarea
                className={`${inputClass} min-h-20 resize-y`}
                value={repro}
                onChange={(event) => setRepro(event.target.value)}
                placeholder="POST /users twice with the same email"
              />
            </Field>
            <Field label="Expected behaviour" hint="Optional">
              <textarea
                className={`${inputClass} min-h-20 resize-y`}
                value={expected}
                onChange={(event) => setExpected(event.target.value)}
                placeholder="The second request returns 409"
              />
            </Field>
          </div>

          <fieldset>
            <legend className="mb-1.5 text-[12px] font-medium text-[var(--color-muted)]">
              Risk mode
            </legend>
            <div className="grid gap-2 sm:grid-cols-3">
              {RISK_MODES.map((mode) => (
                <label
                  key={mode.value}
                  className={`cursor-pointer rounded border px-3 py-2 text-[12px] transition-colors ${
                    riskMode === mode.value
                      ? "border-[var(--color-accent)]/60 bg-[var(--color-accent)]/10"
                      : "border-[var(--color-line)] hover:border-[var(--color-faint)]"
                  }`}
                >
                  <input
                    type="radio"
                    name="risk_mode"
                    value={mode.value}
                    checked={riskMode === mode.value}
                    onChange={(event) => setRiskMode(event.target.value)}
                    className="sr-only"
                  />
                  <span className="block font-medium text-[var(--color-ink)]">{mode.label}</span>
                  <span className="mt-0.5 block text-[11px] text-[var(--color-faint)]">
                    {mode.hint}
                  </span>
                </label>
              ))}
            </div>
            <p className="mt-1.5 text-[11px] text-[var(--color-faint)]">
              Risk mode shifts approval thresholds only. Blocked operations stay blocked in every
              mode.
            </p>
          </fieldset>

          {create.error && <ErrorNote error={create.error} />}

          <Button type="submit" variant="primary" disabled={create.isPending || !selected}>
            {create.isPending ? "Starting…" : "Start Yukti"}
          </Button>
        </form>
      </Panel>
    </>
  );
}
