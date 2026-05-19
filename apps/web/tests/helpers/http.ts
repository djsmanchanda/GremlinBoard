import type { Page, Response } from "@playwright/test";

export interface BadHttpResponse {
  method: string;
  resourceType: string;
  status: number;
  statusText: string;
  url: string;
}

const checkedResourceTypes = new Set(["document", "fetch", "script", "stylesheet", "xhr"]);

export function collectBadHttpResponses(page: Page) {
  const badResponses: BadHttpResponse[] = [];

  page.on("response", (response: Response) => {
    const request = response.request();
    if (response.status() < 400 || !checkedResourceTypes.has(request.resourceType())) {
      return;
    }

    badResponses.push({
      method: request.method(),
      resourceType: request.resourceType(),
      status: response.status(),
      statusText: response.statusText(),
      url: response.url(),
    });
  });

  return {
    all: () => [...badResponses],
    summary: () =>
      badResponses.map((response) => `${response.status} ${response.method} ${response.url}`).join("\n"),
  };
}
