import { describe, expect, it } from "vitest";
import agentsSource from "./Agents.tsx?raw";
import analyticsSource from "./Analytics.tsx?raw";
import backfillsSource from "./Backfills.tsx?raw";
import collectorsSource from "./Collectors.tsx?raw";
import connectorsSource from "./Connectors.tsx?raw";
import consultantSource from "./Consultant.tsx?raw";
import knowledgeSource from "./Knowledge.tsx?raw";
import reportsSource from "./Reports.tsx?raw";
import scheduledJobsSource from "./ScheduledJobs.tsx?raw";
import solutionDeliverySource from "./SolutionDelivery.tsx?raw";
import technicianChatSource from "./TechnicianChat.tsx?raw";
import templatesSource from "./Templates.tsx?raw";
import workflowsSource from "./Workflows.tsx?raw";

const scopedScreens = {
  Agents: agentsSource,
  Analytics: analyticsSource,
  Backfills: backfillsSource,
  Collectors: collectorsSource,
  Connectors: connectorsSource,
  Consultant: consultantSource,
  Knowledge: knowledgeSource,
  Reports: reportsSource,
  ScheduledJobs: scheduledJobsSource,
  SolutionDelivery: solutionDeliverySource,
  TechnicianChat: technicianChatSource,
  Templates: templatesSource,
  Workflows: workflowsSource
};
const legacySelectorName = ["Client", "Id", "Select"].join("");

describe("shell client scope rollout", () => {
  it.each(Object.entries(scopedScreens))("does not render a client selector in %s", (_name, source) => {
    expect(source).not.toContain(legacySelectorName);
    expect(source).not.toContain("setSelectedClientId");
  });
});
