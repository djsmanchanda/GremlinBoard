"use client";

import { useEffect } from "react";

import { fetchSystemSettings } from "@/lib/api";

export function SystemSettingsProvider() {
  useEffect(() => {
    let cancelled = false;
    void fetchSystemSettings()
      .then((settings) => {
        if (cancelled) {
          return;
        }
        const root = document.documentElement;
        root.dataset.theme = settings.appearance.theme_mode;
        root.dataset.density = settings.appearance.board_density;
        root.dataset.grid = String(settings.appearance.show_grid_overlay);
        root.dataset.motion = settings.appearance.reduced_motion ? "reduced" : "full";
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  return null;
}
