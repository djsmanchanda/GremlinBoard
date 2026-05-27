"use client";

import Link from "next/link";
import { useEffect, useMemo, useState, useTransition } from "react";
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

interface SetupProvider {
  provider: string;
  label: string;
  group: "ai" | "runtime";
  description: string;
  keyLabel: string;
  required: boolean;
  aiProviderId?: string;
}

const providerCatalog: SetupProvider[] = [
  {
    provider: "codex",
    label: "Codex",
    group: "ai",
    description: "Primary staged generation provider used by Spec Studio.",
    keyLabel: "api_key",
    required: false,
    aiProviderId: "codex",
  },
  {
    provider: "claude",
    label: "Claude",
    group: "ai",
    description: "Fallback staged generation provider for spec and review passes.",
    keyLabel: "api_key",
    required: false,
    aiProviderId: "claude",
  },
  {
    provider: "newsapi",
    label: "News API",
    group: "runtime",
    description: "External news feed access for headline and briefing widgets.",
    keyLabel: "api_key",
    required: true,
  },
  {
    provider: "football-data",
    label: "Football Data",
    group: "runtime",
    description: "Match and table data for football widgets.",
    keyLabel: "api_key",
    required: true,
  },
  {
    provider: "cricketdata",
    label: "Cricket Data",
    group: "runtime",
    description: "Fixture and scoring data for cricket widgets.",
    keyLabel: "api_key",
    required: true,
  },
  {
    provider: "x",
    label: "X",
    group: "runtime",
    description: "Trending and social stream data where X-backed feeds are enabled.",
    keyLabel: "bearer_token",
    required: true,
  },
];

const emptyCredential = { provider: "", label: "", value: "" };

export function SystemShell() {
  const [context, setContext] = useState<AuthContext | null>(null);
  const [settings, setSettings] = useState<SystemSettings | null>(null);
  const [providers, setProviders] = useState<AIProvider[]>([]);
  const [credentials, setCredentials] = useState<ApiCredential[]>([]);
  const [overview, setOverview] = useState<ObservabilityOverview | null>(null);
  const [credentialDraft, setCredentialDraft] = useState(emptyCredential);
  const [selectedSetupProvider, setSelectedSetupProvider] = useState<string>("newsapi");
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

  const aiStatusMap = useMemo(
    () => new Map(providers.map((provider) => [provider.provider_id, provider])),
    [providers],
  );
  const credentialCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const credential of credentials) {
      counts.set(credential.provider, (counts.get(credential.provider) ?? 0) + 1);
    }
    return counts;
  }, [credentials]);
  const setupItems = providerCatalog.map((item) => {
    const aiProvider = item.aiProviderId ? aiStatusMap.get(item.aiProviderId) : null;
    const hasCredential = (credentialCounts.get(item.provider) ?? 0) > 0;
    const configured = item.group === "ai" ? Boolean(aiProvider) && (hasCredential || !item.required) : hasCredential;
    return {
      ...item,
      configured,
      hasCredential,
      status: aiProvider?.status ?? (hasCredential ? "configured" : "missing"),
    };
  });
  const selectedProviderConfig =
    setupItems.find((item) => item.provider === selectedSetupProvider) ?? setupItems[0] ?? providerCatalog[0];
  const selectedProviderId = selectedProviderConfig.provider;
  const selectedProviderKeyLabel = selectedProviderConfig.keyLabel;
  const missingRequiredProviders = setupItems.filter((item) => item.required && !item.configured);
  const configuredProviderCount = setupItems.filter((item) => item.configured).length;
  const maxMetricValue = Math.max(...(overview?.metrics.map((metric) => metric.metric_value) ?? [1]), 1);
  const overviewPollIntervalSeconds = settings ? Math.max(settings.runtime.monitor_interval_seconds, 15) : 30;

  useEffect(() => {
    if (!settings) {
      return;
    }

    const refreshOverview = () => {
      if (document.visibilityState === "hidden") {
        return;
      }
      void fetchObservabilityOverview()
        .then(setOverview)
        .catch(() => undefined);
    };

    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        refreshOverview();
      }
    };

    const interval = window.setInterval(refreshOverview, overviewPollIntervalSeconds * 1000);
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [overviewPollIntervalSeconds, settings]);

  useEffect(() => {
    setCredentialDraft((current) => {
      const next = {
        provider: selectedProviderId,
        label: current.provider === selectedProviderId && current.label ? current.label : selectedProviderKeyLabel,
        value: current.provider === selectedProviderId ? current.value : "",
      };
      return current.provider === next.provider && current.label === next.label && current.value === next.value ? current : next;
    });
  }, [selectedProviderId, selectedProviderKeyLabel]);

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
          setCredentialDraft({
            provider: credentialDraft.provider,
            label: credentialDraft.label,
            value: "",
          });
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

  const setDefaultProvider = () => {
    if (!settings || !selectedProviderConfig.aiProviderId) {
      return;
    }
    saveSettings({
      ai: {
        ...settings.ai,
        default_provider_id: selectedProviderConfig.aiProviderId,
      },
    });
  };

  return (
    <main className="min-h-screen bg-[#05070a] px-4 py-5 md:px-6 md:py-6">
      <section className="mx-auto max-w-7xl">
        <header className="mb-5 rounded-[24px] border border-white/10 bg-[#090c10] p-5 md:p-6">
          <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
            <div className="max-w-3xl">
              <div className="flex flex-wrap gap-2">
                <span className="rounded border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[10px] uppercase tracking-[0.2em] text-slate-400">
                  System panel
                </span>
                <span className="rounded border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[10px] uppercase tracking-[0.2em] text-slate-400">
                  Deployment setup
                </span>
              </div>
              <h1 className="mt-3 text-3xl font-semibold tracking-tight text-white md:text-4xl">Set up providers for monitored deployments</h1>
              <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-400">
                Add the credentials each widget service needs, choose the AI default for Spec Studio, then watch runtime health and deployment signals in one place.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Link
                href="/"
                className="rounded-[12px] border border-white/10 bg-white/[0.04] px-4 py-2 text-sm text-slate-100 transition hover:bg-white/[0.08]"
              >
                Board
              </Link>
              <Link
                href="/studio"
                className="rounded-[12px] border border-white/10 bg-white/[0.04] px-4 py-2 text-sm text-slate-100 transition hover:bg-white/[0.08]"
              >
                Studio
              </Link>
              <Link
                href={{ pathname: "/system/devtools" }}
                className="rounded-[12px] border border-white/10 bg-white/[0.04] px-4 py-2 text-sm text-slate-100 transition hover:bg-white/[0.08]"
              >
                Devtools
              </Link>
            </div>
          </div>

          <div className="mt-5 grid gap-3 md:grid-cols-4">
            <SummaryCard label="Setup progress" value={`${configuredProviderCount}/${setupItems.length}`} hint="Providers ready for runtime or AI use." />
            <SummaryCard label="Stored secrets" value={String(credentials.length)} hint="Persisted credentials in secure storage." />
            <SummaryCard label="Missing required" value={String(missingRequiredProviders.length)} hint="Providers still missing required setup." />
            <SummaryCard label="Monitor cadence" value={`${overviewPollIntervalSeconds}s`} hint="Deployment overview refresh interval." />
          </div>
        </header>

        {error ? (
          <div className="mb-4 rounded-[18px] border border-rose-300/18 bg-rose-300/8 px-4 py-3 text-sm text-rose-50">
            <p className="text-[10px] uppercase tracking-[0.18em] text-rose-200/80">System warning</p>
            <p className="mt-1">{error}</p>
          </div>
        ) : null}

        {loading || !settings || !overview || !context ? (
          <div className="rounded-[24px] border border-white/10 bg-[#090c10] p-5 md:p-6">
            <p className="text-[10px] uppercase tracking-[0.2em] text-slate-500">Runtime sync</p>
            <h2 className="mt-2 text-2xl font-semibold text-white">Loading system state</h2>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-400">
              Fetching identity, settings, credential inventory, and the latest observability snapshot.
            </p>

            <div className="mt-6 grid gap-3 md:grid-cols-3">
              {Array.from({ length: 3 }).map((_, index) => (
                <div key={index} className="shimmer rounded-[18px] border border-white/10 bg-white/[0.03] p-4">
                  <div className="h-3 w-20 rounded bg-white/10" />
                  <div className="mt-4 h-6 w-2/3 rounded bg-white/10" />
                  <div className="mt-5 h-28 rounded-[14px] bg-white/[0.05]" />
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div className="grid gap-5 xl:grid-cols-[1fr_1.05fr]">
            <section className="space-y-5">
              <Panel
                eyebrow="Setup"
                title="Deployment provider checklist"
                description="Work down this list to make generated and data-backed widgets observable: connect secrets, confirm AI defaults, then watch the runtime cards on the right."
              >
                {missingRequiredProviders.length > 0 ? (
                  <InlineNotice
                    title="Action required"
                    body={`Monitoring can run, but deployments that need ${missingRequiredProviders.map((item) => item.label).join(", ")} will stay incomplete until credentials are stored.`}
                    tone="warning"
                  />
                ) : (
                  <InlineNotice
                    title="Required provider setup is ready"
                    body="Runtime providers that need secrets have at least one stored credential. Keep an eye on the health cards before installing new widgets."
                  />
                )}

                <div className="mt-4 grid gap-3">
                  {setupItems.map((item) => (
                    <button
                      key={item.provider}
                      type="button"
                      onClick={() => setSelectedSetupProvider(item.provider)}
                      className={`w-full rounded-[16px] border px-4 py-3 text-left transition ${
                        selectedProviderConfig.provider === item.provider
                          ? "border-cyan-300/20 bg-cyan-300/8"
                          : "border-white/10 bg-[#07090d] hover:bg-white/[0.05]"
                      }`}
                    >
                      <div className="flex items-center justify-between gap-3">
                        <div>
                          <p className="text-sm font-medium text-white">{item.label}</p>
                          <p className="mt-1 text-xs text-slate-400">{item.description}</p>
                        </div>
                        <span
                          className={`rounded-[10px] border px-2 py-1 text-[10px] uppercase tracking-[0.14em] ${
                            item.configured
                              ? "border-emerald-300/18 bg-emerald-300/10 text-emerald-50"
                              : "border-amber-300/18 bg-amber-300/10 text-amber-50"
                          }`}
                        >
                          {item.configured ? "ready" : "missing"}
                        </span>
                      </div>
                    </button>
                  ))}
                </div>
              </Panel>

              <Panel
                eyebrow="Setup flow"
                title={`Configure ${selectedProviderConfig.label}`}
                description={`${selectedProviderConfig.description} This form stores the secret for monitored widget deployments without changing provider contracts.`}
              >
                <div className="grid gap-3 md:grid-cols-3">
                  <WizardStep step="01" title="Select provider" body="Choose a provider from the deployment checklist." active />
                  <WizardStep
                    step="02"
                    title="Store secret"
                    body={`Save the ${selectedProviderConfig.keyLabel.replaceAll("_", " ")} for ${selectedProviderConfig.label}.`}
                    active={!selectedProviderConfig.configured}
                  />
                  <WizardStep
                    step="03"
                    title="Monitor deployment"
                    body="Watch runtime, widget health, metrics, and timeline cards after the credential is stored."
                    active={selectedProviderConfig.configured}
                  />
                </div>

                <form
                  className="mt-4 space-y-4"
                  onSubmit={(event) => {
                    event.preventDefault();
                    saveCredential();
                  }}
                >
                  <div className="grid gap-3 md:grid-cols-3">
                    <TextField
                      label="Provider"
                      name="provider"
                      autoComplete="off"
                      value={credentialDraft.provider}
                      onChange={(value) => setCredentialDraft({ ...credentialDraft, provider: value })}
                    />
                    <TextField
                      label="Label"
                      name="credential-label"
                      autoComplete="username"
                      value={credentialDraft.label}
                      onChange={(value) => setCredentialDraft({ ...credentialDraft, label: value })}
                    />
                    <SecretField
                      label="Secret"
                      name="credential-secret"
                      value={credentialDraft.value}
                      onChange={(value) => setCredentialDraft({ ...credentialDraft, value })}
                    />
                  </div>

                  <div className="flex flex-wrap gap-2">
                    <ActionButton pending={isPending} type="submit" tone="primary">
                      Store credential
                    </ActionButton>
                    {selectedProviderConfig.aiProviderId ? (
                      <ActionButton pending={isPending} onClick={setDefaultProvider}>
                        Set as default AI provider
                      </ActionButton>
                    ) : null}
                  </div>
                </form>
              </Panel>

              <Panel eyebrow="Credentials" title="Stored credentials">
                {credentials.length === 0 ? (
                  <EmptyState
                    title="No credentials stored"
                    body="Select a provider above to start the setup flow and save the first secret."
                  />
                ) : (
                  <div className="space-y-2">
                    {credentials.map((credential) => (
                      <div key={credential.id} className="flex items-center justify-between gap-3 rounded-[16px] border border-white/10 bg-[#07090d] px-4 py-3">
                        <div className="min-w-0">
                          <p className="text-sm font-medium text-white">{credential.provider}</p>
                          <p className="mt-1 truncate text-xs text-slate-400">
                            {credential.label} · {credential.masked_value}
                          </p>
                        </div>
                        <button
                          type="button"
                          onClick={() => removeCredential(credential.id)}
                          className="rounded-[10px] border border-rose-300/20 bg-rose-300/10 px-3 py-2 text-xs uppercase tracking-[0.14em] text-rose-50 transition hover:bg-rose-300/16"
                        >
                          Delete
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </Panel>

              <CollapsiblePanel eyebrow="Advanced" title="Runtime and appearance settings">
                <div className="grid gap-5">
                  <PreviewCard title="User and session">
                    <div className="grid gap-3 md:grid-cols-2">
                      <StatCard label="User" value={context.user.display_name} hint={context.user.email} />
                      <StatCard label="Session" value={context.session.status} hint={`Expires ${formatTime(context.session.expires_at)}`} />
                    </div>
                  </PreviewCard>

                  <PreviewCard title="Runtime settings">
                    <div className="grid gap-3 md:grid-cols-2">
                      <NumberField
                        label="Monitor interval"
                        value={settings.runtime.monitor_interval_seconds}
                        min={15}
                        max={300}
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
                    </div>
                    <div className="mt-4">
                      <ActionButton pending={isPending} onClick={() => saveSettings({ runtime: settings.runtime })} tone="primary">
                        Save runtime settings
                      </ActionButton>
                    </div>
                  </PreviewCard>

                  <PreviewCard title="Appearance and AI defaults">
                    <div className="grid gap-3 md:grid-cols-2">
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
                    </div>
                    <div className="mt-3 grid gap-3 md:grid-cols-2">
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
                    </div>
                    <div className="mt-4">
                      <ActionButton
                        pending={isPending}
                        onClick={() => saveSettings({ appearance: settings.appearance, ai: settings.ai })}
                        tone="primary"
                      >
                        Save appearance and AI defaults
                      </ActionButton>
                    </div>
                  </PreviewCard>
                </div>
              </CollapsiblePanel>
            </section>

            <section className="space-y-5">
              <Panel eyebrow="Health" title="Runtime overview" description="Top-line board state, widget service counts, and failure visibility.">
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                  {Object.entries(overview.summary).map(([key, value]) => (
                    <SummaryCard key={key} label={key.replaceAll("_", " ")} value={String(value)} hint="Live runtime summary" />
                  ))}
                </div>
              </Panel>

              <Panel eyebrow="Widgets" title="Widget and service health">
                {overview.widget_health.length === 0 ? (
                  <EmptyState title="No widget health samples" body="Add widgets to the board to populate service health and restart data." />
                ) : (
                  <div className="space-y-3">
                    {overview.widget_health.map((item) => (
                      <div key={item.widget_instance_id} className="rounded-[16px] border border-white/10 bg-[#07090d] p-4">
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <p className="truncate text-sm font-medium text-white">{item.title}</p>
                            <p className="mt-1 text-xs text-slate-400">
                              {item.widget_id} · uptime {item.service_uptime_seconds}s · restarts {item.restart_count}
                            </p>
                          </div>
                          <StatusPill tone={healthTone(item.lifecycle_state)}>{item.lifecycle_state}</StatusPill>
                        </div>
                        <p className="mt-3 text-sm leading-6 text-slate-300">{item.status_message ?? "No status message"}</p>
                        <div className="mt-3 grid gap-3 md:grid-cols-3">
                          <MetricBar label="Uptime" value={item.service_uptime_seconds} max={Math.max(item.service_uptime_seconds, 60)} />
                          <MetricBar label="Restarts" value={item.restart_count} max={Math.max(item.restart_count, 1)} />
                          <MetricBar label="Failures" value={item.consecutive_failures} max={Math.max(item.consecutive_failures, 1)} />
                        </div>
                        {item.last_error ? <p className="mt-3 text-xs text-rose-300">{item.last_error}</p> : null}
                      </div>
                    ))}
                  </div>
                )}
              </Panel>

              <Panel eyebrow="Metrics" title="Latest samples">
                {overview.metrics.length === 0 ? (
                  <EmptyState title="No metric samples yet" body="Metrics will appear after the runtime records its first overview window." />
                ) : (
                  <div className="space-y-2">
                    {overview.metrics.slice(0, 12).map((metric, index) => (
                      <MetricRow
                        key={`${metric.metric_name}-${metric.scope_id ?? index}`}
                        label={metric.metric_name}
                        scope={`${metric.scope_type}${metric.scope_id ? ` · ${metric.scope_id}` : ""}`}
                        value={metric.metric_value}
                        percent={Math.max((metric.metric_value / maxMetricValue) * 100, 4)}
                      />
                    ))}
                  </div>
                )}
              </Panel>

              <Panel eyebrow="Timeline" title="Event timeline">
                {overview.timeline.length === 0 ? (
                  <EmptyState title="No timeline events" body="System and widget events will appear here as the runtime records them." />
                ) : (
                  <div className="space-y-3">
                    {overview.timeline.map((item) => (
                      <div key={item.id} className="grid grid-cols-[14px_minmax(0,1fr)] gap-3 rounded-[16px] border border-white/10 bg-[#07090d] p-4">
                        <div className="flex justify-center">
                          <span className={`mt-1 h-2.5 w-2.5 rounded-full ${timelineDotClass(item.level)}`} />
                        </div>
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center justify-between gap-3">
                            <p className="text-sm font-medium text-white">
                              {item.event} · {item.level}
                            </p>
                            <span className="text-[10px] uppercase tracking-[0.14em] text-slate-400">{formatTime(item.created_at)}</span>
                          </div>
                          <p className="mt-2 text-sm leading-6 text-slate-300">{item.message}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
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
  description,
  children,
}: {
  eyebrow: string;
  title: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-[24px] border border-white/10 bg-[#090c10] p-5">
      <p className="text-[10px] uppercase tracking-[0.2em] text-slate-500">{eyebrow}</p>
      <h2 className="mt-2 text-xl font-semibold text-white">{title}</h2>
      {description ? <p className="mt-2 text-sm leading-6 text-slate-400">{description}</p> : null}
      <div className="mt-4">{children}</div>
    </section>
  );
}

function CollapsiblePanel({ eyebrow, title, children }: { eyebrow: string; title: string; children: ReactNode }) {
  return (
    <details className="rounded-[24px] border border-white/10 bg-[#090c10]">
      <summary className="cursor-pointer list-none px-5 py-4">
        <span className="block text-[10px] uppercase tracking-[0.2em] text-slate-500">{eyebrow}</span>
        <span className="mt-2 block text-lg font-semibold text-white">{title}</span>
      </summary>
      <div className="border-t border-white/10 px-5 py-4">{children}</div>
    </details>
  );
}

function PreviewCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-[16px] border border-white/10 bg-[#07090d] p-4">
      <p className="mb-3 text-sm font-medium text-white">{title}</p>
      {children}
    </div>
  );
}

function SummaryCard({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="rounded-[16px] border border-white/10 bg-[#07090d] px-4 py-3">
      <p className="text-[10px] uppercase tracking-[0.16em] text-slate-500">{label}</p>
      <p className="mt-2 text-sm font-medium text-white">{value}</p>
      <p className="mt-1 text-xs text-slate-400">{hint}</p>
    </div>
  );
}

function StatCard({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-[16px] border border-white/10 bg-white/[0.03] p-4">
      <p className="text-[10px] uppercase tracking-[0.16em] text-slate-500">{label}</p>
      <p className="mt-2 text-lg font-semibold text-white">{value}</p>
      {hint ? <p className="mt-1 text-xs text-slate-400">{hint}</p> : null}
    </div>
  );
}

function WizardStep({
  step,
  title,
  body,
  active = false,
}: {
  step: string;
  title: string;
  body: string;
  active?: boolean;
}) {
  return (
    <div className={`rounded-[16px] border p-4 ${active ? "border-cyan-300/20 bg-cyan-300/8" : "border-white/10 bg-[#07090d]"}`}>
      <p className="text-[10px] uppercase tracking-[0.16em] text-slate-500">{step}</p>
      <p className="mt-2 text-sm font-medium text-white">{title}</p>
      <p className="mt-1 text-sm leading-6 text-slate-400">{body}</p>
    </div>
  );
}

function TextField({
  label,
  name,
  autoComplete,
  value,
  onChange,
}: {
  label: string;
  name?: string;
  autoComplete?: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="grid gap-2">
      <span className="text-xs uppercase tracking-[0.14em] text-slate-500">{label}</span>
      <input
        name={name}
        autoComplete={autoComplete}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-[14px] border border-white/10 bg-[#07090d] px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-cyan-300/30"
      />
    </label>
  );
}

function SecretField({
  label,
  name,
  value,
  onChange,
}: {
  label: string;
  name?: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="grid gap-2">
      <span className="text-xs uppercase tracking-[0.14em] text-slate-500">{label}</span>
      <input
        type="password"
        name={name}
        autoComplete="new-password"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-[14px] border border-white/10 bg-[#07090d] px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-cyan-300/30"
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
    <label className="grid gap-2">
      <span className="text-xs uppercase tracking-[0.14em] text-slate-500">{label}</span>
      <input
        type="number"
        min={min}
        max={max}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        className="w-full rounded-[14px] border border-white/10 bg-[#07090d] px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-cyan-300/30"
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
    <label className="grid gap-2">
      <span className="text-xs uppercase tracking-[0.14em] text-slate-500">{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-[14px] border border-white/10 bg-[#07090d] px-3 py-2 text-sm text-slate-100 outline-none"
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
    <label className="flex items-center justify-between rounded-[14px] border border-white/10 bg-[#07090d] px-4 py-3">
      <span className="text-sm text-slate-200">{label}</span>
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
    </label>
  );
}

function ActionButton({
  children,
  onClick,
  pending = false,
  tone = "default",
  type = "button",
}: {
  children: ReactNode;
  onClick?: () => void;
  pending?: boolean;
  tone?: "default" | "primary";
  type?: "button" | "submit";
}) {
  const toneClass =
    tone === "primary"
      ? "border-cyan-300/20 bg-cyan-300/10 text-cyan-50 hover:bg-cyan-300/16"
      : "border-white/10 bg-white/[0.04] text-slate-100 hover:bg-white/[0.08]";
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={pending}
      className={`rounded-[12px] border px-4 py-2 text-sm transition disabled:cursor-not-allowed disabled:opacity-50 ${toneClass}`}
    >
      {pending ? "Saving..." : children}
    </button>
  );
}

function InlineNotice({
  title,
  body,
  tone = "default",
}: {
  title: string;
  body: string;
  tone?: "default" | "warning";
}) {
  return (
    <div
      className={`rounded-[16px] border px-4 py-3 ${
        tone === "warning" ? "border-amber-300/18 bg-amber-300/8 text-amber-50" : "border-white/10 bg-white/[0.04] text-slate-100"
      }`}
    >
      <p className="text-sm font-medium">{title}</p>
      <p className={`mt-1 text-sm leading-6 ${tone === "warning" ? "text-amber-50/80" : "text-slate-400"}`}>{body}</p>
    </div>
  );
}

function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-[16px] border border-dashed border-white/12 bg-white/[0.03] p-5 text-center">
      <p className="text-sm font-medium text-white">{title}</p>
      <p className="mt-2 text-sm leading-6 text-slate-400">{body}</p>
    </div>
  );
}

function StatusPill({ tone, children }: { tone: "good" | "warning" | "danger" | "neutral"; children: ReactNode }) {
  const toneClass =
    tone === "good"
      ? "border-emerald-300/18 bg-emerald-300/10 text-emerald-50"
      : tone === "warning"
        ? "border-amber-300/18 bg-amber-300/10 text-amber-50"
        : tone === "danger"
          ? "border-rose-300/18 bg-rose-300/10 text-rose-50"
          : "border-white/10 bg-white/[0.04] text-slate-200";
  return <span className={`rounded-[10px] border px-3 py-1 text-xs uppercase tracking-[0.14em] ${toneClass}`}>{children}</span>;
}

function MetricBar({ label, value, max }: { label: string; value: number; max: number }) {
  const width = Math.max((value / Math.max(max, 1)) * 100, value > 0 ? 8 : 0);
  return (
    <div className="rounded-[14px] border border-white/10 bg-white/[0.03] p-3">
      <div className="flex items-center justify-between gap-3">
        <p className="text-[10px] uppercase tracking-[0.14em] text-slate-500">{label}</p>
        <span className="text-xs text-slate-300">{value}</span>
      </div>
      <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/5">
        <div className="h-full rounded-full bg-cyan-300/70" style={{ width: `${width}%` }} />
      </div>
    </div>
  );
}

function MetricRow({
  label,
  scope,
  value,
  percent,
}: {
  label: string;
  scope: string;
  value: number;
  percent: number;
}) {
  return (
    <div className="rounded-[16px] border border-white/10 bg-[#07090d] p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-white">{label}</p>
          <p className="mt-1 truncate text-xs text-slate-400">{scope}</p>
        </div>
        <span className="text-sm font-medium text-white">{value}</span>
      </div>
      <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/5">
        <div className="h-full rounded-full bg-cyan-300/70" style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}

function healthTone(state: string) {
  if (state === "running" || state === "created") {
    return "good";
  }
  if (state === "paused" || state === "installing") {
    return "warning";
  }
  if (state === "error") {
    return "danger";
  }
  return "neutral";
}

function timelineDotClass(level: string) {
  if (level.toLowerCase() === "error") {
    return "bg-rose-300";
  }
  if (level.toLowerCase() === "warning") {
    return "bg-amber-300";
  }
  return "bg-cyan-300";
}

function formatTime(value: string) {
  return new Date(value).toLocaleString();
}
