phase("fan-out");
const parts = await parallel([
  () => agent("用一句话说明什么是 CI。只输出一句话。", { label: "ci", phase: "fan-out" }),
  () => agent("用一句话说明什么是 CD。只输出一句话。", { label: "cd", phase: "fan-out" }),
  () => agent("用一句话说明什么是 IaC。只输出一句话。", { label: "iac", phase: "fan-out" }),
]);

phase("fan-in");
const good = parts.filter(Boolean);
const summary = await agent(
  "把下面三句话合并成一段不超过 80 字的总述，只输出总述：\n" +
    good.map((t, i) => (i + 1) + ". " + t).join("\n"),
  { label: "summary", phase: "fan-in" }
);
return { count: good.length, parts, summary };
