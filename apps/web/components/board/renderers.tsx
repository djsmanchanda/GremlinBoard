"use client";

import { Component, type ComponentType, type ErrorInfo, type ReactNode, useEffect, useState } from "react";

import { BlueprintRenderer } from "@/components/board/blueprint-renderer";
import type { ModuleRendererTarget, WidgetManifest, WidgetRendererProps } from "@/lib/types";

type WidgetRendererComponent = ComponentType<WidgetRendererProps>;

const rendererCache = new Map<string, Promise<WidgetRendererComponent>>();

function isBlueprintManifest(manifest: WidgetManifest) {
  return manifest.renderer.kind === "blueprint";
}

function getModuleRenderer(manifest: WidgetManifest): ModuleRendererTarget {
  if (manifest.renderer.kind === "blueprint") {
    throw new Error("Blueprint manifests do not use module renderers.");
  }
  return manifest.renderer;
}

function getRendererCacheKey(manifest: WidgetManifest) {
  if (manifest.renderer.kind === "blueprint") {
    return `${manifest.id}:blueprint`;
  }
  return `${manifest.id}:${manifest.renderer.module}:${manifest.renderer.export_name}`;
}

function getRendererLoadError(error: unknown) {
  return error instanceof Error ? error.message : "Renderer failed to load.";
}

function UnsupportedWidgetRenderer({ manifest, reason }: { manifest: WidgetManifest; reason: string }) {
  return (
    <div className="flex h-full min-h-[180px] items-center justify-center rounded-panel border border-dashed border-amber-300/20 bg-amber-300/8 p-5 text-center">
      <div>
        <p className="text-[11px] uppercase tracking-[0.2em] text-amber-100/75">Renderer unavailable</p>
        <p className="mt-3 text-sm font-medium text-white">{reason}</p>
        <p className="mt-2 text-sm leading-6 text-slate-300">
          {manifest.renderer.kind === "blueprint"
            ? `${manifest.id}#blueprint`
            : `${manifest.renderer.module}#${manifest.renderer.export_name}`}
        </p>
      </div>
    </div>
  );
}

function LoadingWidgetRenderer({ manifest }: { manifest: WidgetManifest }) {
  return (
    <div className="flex h-full min-h-[180px] items-center justify-center rounded-panel border border-dashed border-edge p-5 text-center">
      <div>
        <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">Renderer loading</p>
        <p className="mt-3 text-sm text-slate-300">Loading renderer for {manifest.name}...</p>
      </div>
    </div>
  );
}

class WidgetRendererBoundary extends Component<
  { children: ReactNode; manifest: WidgetManifest },
  { message: string | null }
> {
  state = { message: null as string | null };

  static getDerivedStateFromError(error: Error) {
    return { message: error.message };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error(`Renderer failed for widget ${this.props.manifest.id}`, error, errorInfo);
  }

  render() {
    if (this.state.message) {
      return <UnsupportedWidgetRenderer manifest={this.props.manifest} reason={this.state.message} />;
    }

    return this.props.children;
  }
}

function parseRendererModule(manifest: WidgetManifest) {
  const renderer = getModuleRenderer(manifest);
  const match = /^@widgets\/([a-z][a-z0-9_-]+)\/renderer$/.exec(renderer.module);
  if (!match) {
    throw new Error(`Renderer module '${renderer.module}' is not supported.`);
  }
  if (match[1] !== manifest.id) {
    throw new Error("Renderer module does not match the widget manifest id.");
  }
  return match[1];
}

async function importRendererModule(widgetId: string) {
  return import(`../../../../widgets/${widgetId}/renderer`);
}

async function loadWidgetRenderer(manifest: WidgetManifest): Promise<WidgetRendererComponent> {
  const renderer = getModuleRenderer(manifest);
  if (renderer.target !== "react") {
    throw new Error(`Renderer target '${renderer.target}' is not supported.`);
  }

  const widgetId = parseRendererModule(manifest);
  const rendererModule = (await importRendererModule(widgetId)) as Record<string, unknown>;
  const component = rendererModule[renderer.export_name];

  if (typeof component !== "function") {
    throw new Error(`Renderer export '${renderer.export_name}' was not found.`);
  }

  return component as WidgetRendererComponent;
}

function getRendererPromise(manifest: WidgetManifest) {
  const cacheKey = getRendererCacheKey(manifest);
  const cached = rendererCache.get(cacheKey);
  if (cached) {
    return cached;
  }

  const pending = loadWidgetRenderer(manifest);
  rendererCache.set(cacheKey, pending);
  return pending;
}

export function WidgetRenderer(props: WidgetRendererProps) {
  // Blueprint-kind manifests (generated widgets) route to the universal
  // renderer shipped with the app — no dynamic import, works in production
  // standalone builds. A widget payload carrying a blueprint document gets the
  // same treatment. Module-kind built-ins keep the dynamic import path.
  if (isBlueprintManifest(props.manifest) || props.widget.blueprint != null) {
    return (
      <WidgetRendererBoundary key={getRendererCacheKey(props.manifest)} manifest={props.manifest}>
        <BlueprintRenderer {...props} />
      </WidgetRendererBoundary>
    );
  }

  return <ModuleWidgetRenderer {...props} />;
}

function ModuleWidgetRenderer(props: WidgetRendererProps) {
  const cacheKey = getRendererCacheKey(props.manifest);
  const [RendererComponent, setRendererComponent] = useState<WidgetRendererComponent | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setRendererComponent(null);
    setLoadError(null);

    void getRendererPromise(props.manifest)
      .then((component) => {
        if (!cancelled) {
          setRendererComponent(() => component);
        }
      })
      .catch((error) => {
        rendererCache.delete(cacheKey);
        if (!cancelled) {
          setLoadError(getRendererLoadError(error));
        }
      });

    return () => {
      cancelled = true;
    };
  }, [cacheKey, props.manifest]);

  if (loadError) {
    return <UnsupportedWidgetRenderer manifest={props.manifest} reason={loadError} />;
  }

  if (!RendererComponent) {
    return <LoadingWidgetRenderer manifest={props.manifest} />;
  }

  return (
    <WidgetRendererBoundary key={cacheKey} manifest={props.manifest}>
      <RendererComponent {...props} />
    </WidgetRendererBoundary>
  );
}
