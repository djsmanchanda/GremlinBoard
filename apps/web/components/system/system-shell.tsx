"use client";

import Link from "next/link";
import { useEffect, useState, useTransition } from "react";
import type { ReactNode } from "react";

import {
  deleteApiCredential,
  fetchAIProviders,
  fetchApiCredentials,
  fetchObservabilityOverview,
  fetchSystemContext,
  fetchSystemSettings,
  updateSystemSettings,
  upsertApiCredential,
} from "@/lib/api";
import type {
  AIProvider,
  ApiCredential,
  AuthContext,
  ObservabilityOverview,
  SystemSettings,
} from "@/lib/types";

const emptyCredential = { provider: "", label: "", value: "" };

export function SystemShell() {
  const [context, setContext] = useState<AuthContext | null>(null);
  const [settings, setSettings] = useState<SystemSettings | null>(null);
  const [providers, setProviders] = useState<AIProvider[]>([]);
  const [credentials, setCredentials] = useState<ApiCredential[]>([]);
  const [overview, setOverview] = useState<ObservabilityOverview | null>(null);
  const [credentialDraft, setCredentialDraft] = useState(emptyCredential);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [contextResponse, settingsResponse, providersResponse, credentialsResponse, overviewResponse] =
          await Promise.all([
            fetchSystemContext(),
            fetchSystemSettings(),
            fetchAIProviders(),
            fetchApiCredentials(),
            fetchObservabilityOverview(),
          ]);
        if (cancelled) {
          return;
        }
        setContext(contextResponse);
        setSettings(settingsResponse);
        setProviders(providersResponse);
        setCredentials(credentialsResponse);
        setOverview(overviewResponse);
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : "Failed to load system panel");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const interval = window.setInterval(() => {
      void fetchObservabilityOverview()
        .then(setOverview)
        .catch(() => undefined);
    }, 8000);
    return () => window.clearInterval(interval);
  }, []);

  const saveSettings = (next: Partial<SystemSettings>) => {
    setError(null);
    startTransition(() => {
      void updateSystemSettings(next)
        .then(setSettings)
        .catch((requestError) => {
          setError(requestError instanceof Error ? requestError.message : "Failed to save settings");
        });
    });
  };

  const saveCredential = () => {
    if (!credentialDraft.provider.trim() || !credentialDraft.label.trim() || !credentialDraft.value.trim()) {
      setError("Provider, label, and value are required for credentials.");
      return;
    }
    setError(null);
    startTransition(() => {
      void upsertApiCredential(credentialDraft)
        .then((credential) => {
          setCredentials((items) => [credential, ...items.filter((item) => item.id !== credential.id)]);
          setCredentialDraft(emptyCredential);
        })
        .catch((requestError) => {
          setError(requestError instanceof Error ? requestError.message : "Failed to save credential");
        });
    });
  };

  const removeCredential = (credentialId: string) => {
    setError(null);
    startTransition(() => {
      void deleteApiCredential(credentialId)
        .then(() => setCredentials((items) => items.filter((item) => item.id !== credentialId)))
        .catch((requestError) => {
          setError(requestError instanceof Error ? requestError.message : "Failed to delete credential");
        });
    });
  };

  return (
    <main className="min-h-screen px-4 py-6 md:px-6">
      <section className="mx-auto max-w-7xl">
        <header className="mb-6 flex flex-col gap-4 rounded-[32px] border border-white/10 bg-white/5 p-5 backdrop-blur md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-xs uppercase tracking-[0.3em] text-cyan-300/80">Platform Control Surface</p>
            <h1 className="mt-2 text-4xl font-semibold tracking-tight text-white">System Panel</h1>
            <p className="mt-3 max-w-3xl text-sm text-slate-300">
              Production-readiness controls for runtime, observability, AI providers, credentials, and session foundation.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Link
              href="/"
              className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm text-slate-200 transition hover:bg-white/10"
            >
              Board
            </Link>
            <Link
              href="/studio"
              className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm text-slate-200 transition hover:bg-white/10"
            >
              Studio
            </Link>
          </div>
        </header>

        {error ? (
          <div className="mb-4 rounded-2xl border border-rose-400/20 bg-rose-400/10 px-4 py-3 text-sm text-rose-100">
            {error}
          </div>
        ) : null}

        {loading || !settings || !overview || !context ? (
          <div className="rounded-[28px] border border-white/10 bg-white/5 p-8 text-sm text-slate-300">
            Loading system state...
          </div>
        ) : (
          <div className="grid gap-6 xl:grid-cols-[1.08fr_0.92fr]">
            <section className="space-y-6">
              <Panel eyebrow="Identity" title="User and session foundation">
                <div className="grid gap-3 md:grid-cols-2">
                  <StatCard label="User" value={context.user.display_name} hint={context.user.email} />
                  <StatCard label="Session" value={context.session.status} hint={`Expires ${formatTime(context.session.expires_at)}`} />
                </div>
              </Panel>

              <Panel eyebrow="Runtime" title="Runtime settings">
                <SettingsGrid>
                  <NumberField
                    label="Monitor interval"
                    value={settings.runtime.monitor_interval_seconds}
                    min={1}
                    max={60}
                    onChange={(value) =>
                      setSettings({
                        ...settings,
                        runtime: { ...settings.runtime, monitor_interval_seconds: value },
                      })
                    }
                  />
                  <NumberField
                    label="Metrics retention"
                    value={settings.runtime.metrics_retention_points}
                    min={10}
                    max={1000}
                    onChange={(value) =>
                      setSettings({
                        ...settings,
                        runtime: { ...settings.runtime, metrics_retention_points: value },
                      })
                    }
                  />
                  <NumberField
                    label="Log view limit"
                    value={settings.runtime.log_view_limit}
                    min={20}
                    max={1000}
                    onChange={(value) =>
                      setSettings({
                        ...settings,
                        runtime: { ...settings.runtime, log_view_limit: value },
                      })
                    }
                  />
                </SettingsGrid>
                <SaveButton
                  pending={isPending}
                  onClick={() => saveSettings({ runtime: settings.runtime })}
                  label="Save runtime settings"
                />
              </Panel>

              <Panel eyebrow="Appearance" title="Theme and layout settings">
                <SettingsGrid>
                  <SelectField
                    label="Theme mode"
                    value={settings.appearance.theme_mode}
                    options={["control", "ember", "steel"]}
                    onChange={(value) =>
                      setSettings({
                        ...settings,
                        appearance: { ...settings.appearance, theme_mode: value },
                      })
                    }
                  />
                  <SelectField
                    label="Board density"
                    value={settings.appearance.board_density}
                    options={["comfortable", "compact"]}
                    onChange={(value) =>
                      setSettings({
                        ...settings,
                        appearance: { ...settings.appearance, board_density: value },
                      })
                    }
                  />
                </SettingsGrid>
                <ToggleRow
                  label="Show grid overlay"
                  checked={settings.appearance.show_grid_overlay}
                  onChange={(checked) =>
                    setSettings({
                      ...settings,
                      appearance: { ...settings.appearance, show_grid_overlay: checked },
                    })
                  }
                />
                <ToggleRow
                  label="Reduced motion"
                  checked={settings.appearance.reduced_motion}
                  onChange={(checked) =>
                    setSettings({
                      ...settings,
                      appearance: { ...settings.appearance, reduced_motion: checked },
                    })
                  }
                />
                <SaveButton
                  pending={isPending}
                  onClick={() => saveSettings({ appearance: settings.appearance })}
                  label="Save appearance"
                />
              </Panel>

              <Panel eyebrow="AI Layer" title="Provider defaults and fallback">
                <SettingsGrid>
                  <SelectField
                    label="Default provider"
                    value={settings.ai.default_provider_id}
                    options={providers.map((provider) => provider.provider_id)}
                    onChange={(value) =>
                      setSettings({
                        ...settings,
                        ai: { ...settings.ai, default_provider_id: value },
                      })
                    }
                  />
                  <TextField
                    label="Fallback providers"
                    value={settings.ai.fallback_provider_ids.join(", ")}
                    onChange={(value) =>
                      setSettings({
                        ...settings,
                        ai: {
                          ...settings.ai,
                          fallback_provider_ids: splitCsv(value),
                        },
                      })
                    }
                  />
                </SettingsGrid>
                <TextField
                  label="Enabled providers"
                  value={settings.ai.enabled_provider_ids.join(", ")}
                  onChange={(value) =>
                    setSettings({
                      ...settings,
                      ai: {
                        ...settings.ai,
                        enabled_provider_ids: splitCsv(value),
                      },
                    })
                  }
                />
                <SaveButton pending={isPending} onClick={() => saveSettings({ ai: settings.ai })} label="Save AI settings" />
              </Panel>

              <Panel eyebrow="Secrets" title="API key management">
                <div className="space-y-3">
                  {credentials.map((credential) => (
                    <div key={credential.id} className="rounded-2xl border border-white/10 bg-slate-950/50 p-4">
                      <div className="flex items-center justify-between gap-3">
                        <div>
                          <p className="text-sm font-medium text-white">{credential.provider}</p>
                          <p className="text-xs text-slate-400">
                            {credential.label} · {credential.masked_value}
                          </p>
                        </div>
                        <button
                          type="button"
                          onClick={() => removeCredential(credential.id)}
                          className="rounded-full border border-rose-300/30 bg-rose-300/15 px-3 py-1 text-xs text-rose-50 transition hover:bg-rose-300/20"
                        >
                          Delete
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
                <div className="mt-4 grid gap-3 md:grid-cols-3">
                  <TextField
                    label="Provider"
                    value={credentialDraft.provider}
                    onChange={(value) => setCredentialDraft({ ...credentialDraft, provider: value })}
                  />
                  <TextField
                    label="Label"
                    value={credentialDraft.label}
                    onChange={(value) => setCredentialDraft({ ...credentialDraft, label: value })}
                  />
                  <TextField
                    label="Secret"
                    value={credentialDraft.value}
                    onChange={(value) => setCredentialDraft({ ...credentialDraft, value: value })}
                  />
                </div>
                <SaveButton pending={isPending} onClick={saveCredential} label="Store credential" />
              </Panel>
            </section>

            <section className="space-y-6">
              <Panel eyebrow="Health" title="Runtime and service dashboard">
                <div className="grid gap-3 md:grid-cols-2">
                  {Object.entries(overview.summary).map(([key, value]) => (
                    <StatCard key={key} label={key.replaceAll("_", " ")} value={String(value)} />
                  ))}
                </div>
              </Panel>

              <Panel eyebrow="Widgets" title="Widget and service health">
                <div className="space-y-3">
                  {overview.widget_health.map((item) => (
                    <div key={item.widget_instance_id} className="rounded-2xl border border-white/10 bg-slate-950/50 p-4">
                      <div className="flex items-center justify-between gap-3">
                        <div>
                          <p className="text-sm font-medium text-white">{item.title}</p>
                          <p className="text-xs text-slate-400">
                            {item.widget_id} · uptime {item.service_uptime_seconds}s · restarts {item.restart_count}
                          </p>
                        </div>
                        <span className="rounded-full border border-white/10 px-3 py-1 text-xs uppercase tracking-[0.16em] text-slate-200">
                          {item.lifecycle_state}
                        </span>
                      </div>
                      <p className="mt-2 text-sm text-slate-300">{item.status_message ?? "No status message"}</p>
                      {item.last_error ? <p className="mt-2 text-xs text-rose-300">{item.last_error}</p> : null}
                    </div>
                  ))}
                </div>
              </Panel>

              <Panel eyebrow="Metrics" title="Latest metric samples">
                <div className="space-y-3">
                  {overview.metrics.slice(0, 12).map((metric, index) => (
                    <div key={`${metric.metric_name}-${metric.scope_id ?? index}`} className="rounded-2xl border border-white/10 bg-slate-950/50 p-4">
                      <div className="flex items-center justify-between gap-3">
                        <p className="text-sm font-medium text-white">{metric.metric_name}</p>
                        <span className="text-xs text-slate-400">{metric.metric_value}</span>
                      </div>
                      <p className="mt-2 text-xs text-slate-400">
                        {metric.scope_type}
                        {metric.scope_id ? ` · ${metric.scope_id}` : ""}
                      </p>
                    </div>
                  ))}
                </div>
              </Panel>

              <Panel eyebrow="Timeline" title="Error and event timeline">
                <div className="space-y-3">
                  {overview.timeline.map((item) => (
                    <div key={item.id} className="rounded-2xl border border-white/10 bg-slate-950/50 p-4">
                      <div className="flex items-center justify-between gap-3">
                        <p className="text-sm font-medium text-white">
                          {item.event} · {item.level}
                        </p>
                        <span className="text-xs text-slate-400">{formatTime(item.created_at)}</span>
                      </div>
                      <p className="mt-2 text-sm text-slate-300">{item.message}</p>
                    </div>
                  ))}
                </div>
              </Panel>
            </section>
          </div>
        )}
      </section>
    </main>
  );
}

function Panel({
  eyebrow,
  title,
  children,
}: {
  eyebrow: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-[28px] border border-white/10 bg-white/5 p-5">
      <p className="text-xs uppercase tracking-[0.24em] text-slate-500">{eyebrow}</p>
      <h2 className="mt-2 text-xl font-semibold text-white">{title}</h2>
      <div className="mt-4">{children}</div>
    </section>
  );
}

function StatCard({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-slate-950/60 p-4">
      <p className="text-[11px] uppercase tracking-[0.18em] text-slate-500">{label}</p>
      <p className="mt-2 text-xl font-semibold text-white">{value}</p>
      {hint ? <p className="mt-2 text-xs text-slate-400">{hint}</p> : null}
    </div>
  );
}

function SettingsGrid({ children }: { children: ReactNode }) {
  return <div className="grid gap-3 md:grid-cols-2">{children}</div>;
}

function TextField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="block">
      <span className="mb-2 block text-sm text-slate-300">{label}</span>
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-2xl border border-white/10 bg-slate-950/80 px-4 py-3 text-sm text-slate-100 outline-none focus:border-cyan-300/40"
      />
    </label>
  );
}

function NumberField({
  label,
  value,
  onChange,
  min,
  max,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  min: number;
  max: number;
}) {
  return (
    <label className="block">
      <span className="mb-2 block text-sm text-slate-300">{label}</span>
      <input
        type="number"
        min={min}
        max={max}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        className="w-full rounded-2xl border border-white/10 bg-slate-950/80 px-4 py-3 text-sm text-slate-100 outline-none focus:border-cyan-300/40"
      />
    </label>
  );
}

function SelectField({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (value: string) => void;
}) {
  return (
    <label className="block">
      <span className="mb-2 block text-sm text-slate-300">{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-2xl border border-white/10 bg-slate-950/80 px-4 py-3 text-sm text-slate-100 outline-none focus:border-cyan-300/40"
      >
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </label>
  );
}

function ToggleRow({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="mt-3 flex items-center justify-between rounded-2xl border border-white/10 bg-slate-950/60 px-4 py-3">
      <span className="text-sm text-slate-200">{label}</span>
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
    </label>
  );
}

function SaveButton({ pending, onClick, label }: { pending: boolean; onClick: () => void; label: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={pending}
      className="mt-4 rounded-full border border-cyan-300/30 bg-cyan-300/15 px-4 py-2 text-sm text-cyan-50 transition hover:bg-cyan-300/20 disabled:cursor-not-allowed disabled:opacity-50"
    >
      {pending ? "Saving..." : label}
    </button>
  );
}

function splitCsv(value: string) {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function formatTime(value: string) {
  return new Date(value).toLocaleString();
}
