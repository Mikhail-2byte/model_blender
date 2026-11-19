import { mkdir, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { Client } from "../../.local/studio/plugins/blender-agent-studio/node_modules/@modelcontextprotocol/client/dist/index.mjs";
import { StdioClientTransport } from "../../.local/studio/plugins/blender-agent-studio/node_modules/@modelcontextprotocol/client/dist/stdio.mjs";

if (!process.argv[2]) throw new Error("Pass a new output directory.");
const output = resolve(process.argv[2]);
await mkdir(output);
const client = new Client({ name: "droneworks-workshop-check", version: "1.0.0" });
const transport = new StdioClientTransport({
  command: "powershell.exe",
  args: ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", join(import.meta.dir, "start-blender-mcp.ps1")],
  stderr: "pipe",
  maxBufferSize: 64_000_000,
});
let stderr = "";
transport.stderr?.on("data", (chunk) => { stderr += chunk.toString(); });
try {
  await client.connect(transport);
  const { tools } = await client.listTools();
  const result = await client.callTool({
    name: "blender_check_setup",
    arguments: { outputDir: join(output, "doctor"), timeoutMs: 180000 },
  }, { timeout: 195000 });
  let images = 0;
  const content = result.content as Array<{ type: string; data: string; mimeType: string }>;
  for (const item of content) {
    if (item.type !== "image") continue;
    const extension = item.mimeType === "image/jpeg" ? "jpg" : "png";
    await writeFile(join(output, "mcp-preview-" + images++ + "." + extension), Buffer.from(item.data, "base64"));
  }
  await writeFile(join(output, "mcp-stdio.json"), JSON.stringify({
    toolCount: tools.length, images, isError: Boolean(result.isError),
    structuredContent: result.structuredContent, stderr,
  }, null, 2));
  if (result.isError || result.structuredContent?.status !== "pass" || images === 0) {
    throw new Error("Blender MCP check failed; see mcp-stdio.json");
  }
  console.log("Blender MCP stdio passed", { tools: tools.length, images, output });
} finally {
  await client.close();
}
