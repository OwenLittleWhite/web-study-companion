(function () {
  "use strict";

  function appendText(parent, value) {
    const parts = String(value).split("\n");
    parts.forEach((part, index) => {
      if (index) parent.append(document.createElement("br"));
      if (part) parent.append(document.createTextNode(part));
    });
  }

  function safeHref(value) {
    const href = value.trim();
    return /^(https?:\/\/|mailto:)/i.test(href) ? href : null;
  }

  function appendInline(parent, source) {
    const rules = [
      { pattern: /`([^`\n]+)`/, tag: "code", group: 1 },
      { pattern: /\[([^\]\n]+)\]\(([^)\s]+)\)/, tag: "a", group: 1, hrefGroup: 2 },
      { pattern: /<((?:https?:\/\/|mailto:)[^>\s]+)>/i, tag: "a", group: 1, hrefGroup: 1 },
      { pattern: /\*\*([^*\n]+)\*\*/, tag: "strong", group: 1, recursive: true },
      { pattern: /__([^_\n]+)__/, tag: "strong", group: 1, recursive: true },
      { pattern: /~~([^~\n]+)~~/, tag: "del", group: 1, recursive: true },
      { pattern: /\*([^*\n]+)\*/, tag: "em", group: 1, recursive: true },
      { pattern: /_([^_\n]+)_/, tag: "em", group: 1, recursive: true }
    ];
    let remaining = String(source);
    while (remaining) {
      let selected = null;
      for (const rule of rules) {
        const match = rule.pattern.exec(remaining);
        if (match && (!selected || match.index < selected.match.index)) selected = { rule, match };
      }
      if (!selected) {
        appendText(parent, remaining);
        return;
      }
      appendText(parent, remaining.slice(0, selected.match.index));
      const { rule, match } = selected;
      const value = match[rule.group];
      if (rule.tag === "a") {
        const href = safeHref(match[rule.hrefGroup]);
        if (!href) {
          appendText(parent, match[0]);
        } else {
          const link = document.createElement("a");
          link.href = href;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          appendInline(link, value);
          parent.append(link);
        }
      } else {
        const node = document.createElement(rule.tag);
        if (rule.recursive) appendInline(node, value);
        else node.textContent = value;
        parent.append(node);
      }
      remaining = remaining.slice(selected.match.index + match[0].length);
    }
  }

  function splitTableRow(line) {
    let value = line.trim();
    if (value.startsWith("|")) value = value.slice(1);
    if (value.endsWith("|")) value = value.slice(0, -1);
    return value.split("|").map((cell) => cell.trim());
  }

  function isTableDivider(line) {
    const cells = splitTableRow(line);
    return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
  }

  function isBlockStart(lines, index) {
    const line = lines[index] || "";
    return /^ {0,3}(#{1,6})\s+/.test(line)
      || /^ {0,3}```/.test(line)
      || /^\s*>\s?/.test(line)
      || /^\s*(?:[-+*]|\d+\.)\s+/.test(line)
      || /^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line)
      || (index + 1 < lines.length && line.includes("|") && isTableDivider(lines[index + 1]));
  }

  function appendTable(fragment, lines, start) {
    const headers = splitTableRow(lines[start]);
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const headerRow = document.createElement("tr");
    headers.forEach((header) => {
      const cell = document.createElement("th");
      appendInline(cell, header);
      headerRow.append(cell);
    });
    thead.append(headerRow);
    table.append(thead);
    const tbody = document.createElement("tbody");
    let index = start + 2;
    while (index < lines.length && lines[index].trim() && lines[index].includes("|")) {
      const row = document.createElement("tr");
      const values = splitTableRow(lines[index]);
      headers.forEach((_header, column) => {
        const cell = document.createElement("td");
        appendInline(cell, values[column] || "");
        row.append(cell);
      });
      tbody.append(row);
      index += 1;
    }
    table.append(tbody);
    fragment.append(table);
    return index;
  }

  function renderMarkdownSafe(container, markdown) {
    container.textContent = "";
    const fragment = document.createDocumentFragment();
    const lines = String(markdown || "").replace(/\r\n?/g, "\n").split("\n");
    let index = 0;
    while (index < lines.length) {
      const line = lines[index];
      if (!line.trim()) {
        index += 1;
        continue;
      }

      const fence = /^ {0,3}```\s*([A-Za-z0-9_-]*)\s*$/.exec(line);
      if (fence) {
        const codeLines = [];
        index += 1;
        while (index < lines.length && !/^ {0,3}```\s*$/.test(lines[index])) {
          codeLines.push(lines[index]);
          index += 1;
        }
        if (index < lines.length) index += 1;
        const pre = document.createElement("pre");
        const code = document.createElement("code");
        if (fence[1]) code.className = `language-${fence[1].toLowerCase()}`;
        code.textContent = codeLines.join("\n");
        pre.append(code);
        fragment.append(pre);
        continue;
      }

      const heading = /^ {0,3}(#{1,6})\s+(.+?)\s*#*\s*$/.exec(line);
      if (heading) {
        const node = document.createElement(`h${heading[1].length}`);
        appendInline(node, heading[2]);
        fragment.append(node);
        index += 1;
        continue;
      }

      if (/^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
        fragment.append(document.createElement("hr"));
        index += 1;
        continue;
      }

      if (index + 1 < lines.length && line.includes("|") && isTableDivider(lines[index + 1])) {
        index = appendTable(fragment, lines, index);
        continue;
      }

      if (/^\s*>\s?/.test(line)) {
        const quoteLines = [];
        while (index < lines.length && /^\s*>\s?/.test(lines[index])) {
          quoteLines.push(lines[index].replace(/^\s*>\s?/, ""));
          index += 1;
        }
        const quote = document.createElement("blockquote");
        renderMarkdownSafe(quote, quoteLines.join("\n"));
        fragment.append(quote);
        continue;
      }

      const listMatch = /^\s*(?:([-+*])|(\d+)\.)\s+(.+)$/.exec(line);
      if (listMatch) {
        const ordered = Boolean(listMatch[2]);
        const list = document.createElement(ordered ? "ol" : "ul");
        while (index < lines.length) {
          const item = /^\s*(?:([-+*])|(\d+)\.)\s+(.+)$/.exec(lines[index]);
          if (!item || Boolean(item[2]) !== ordered) break;
          const listItem = document.createElement("li");
          const task = /^\[([ xX])\]\s+(.+)$/.exec(item[3]);
          if (task) {
            const checkbox = document.createElement("input");
            checkbox.type = "checkbox";
            checkbox.checked = task[1].toLowerCase() === "x";
            checkbox.disabled = true;
            listItem.className = "task-item";
            listItem.append(checkbox);
            appendInline(listItem, task[2]);
          } else {
            appendInline(listItem, item[3]);
          }
          list.append(listItem);
          index += 1;
        }
        fragment.append(list);
        continue;
      }

      const paragraphLines = [line.trim()];
      index += 1;
      while (index < lines.length && lines[index].trim() && !isBlockStart(lines, index)) {
        paragraphLines.push(lines[index].trim());
        index += 1;
      }
      const paragraph = document.createElement("p");
      appendInline(paragraph, paragraphLines.join(" "));
      fragment.append(paragraph);
    }
    container.append(fragment);
  }

  window.renderMarkdownSafe = renderMarkdownSafe;
})();
