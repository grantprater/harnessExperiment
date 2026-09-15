/**
 * Mineflayer Sidecar Bridge for Reticle Cognitive Harness.
 * 
 * STRICT VISUAL & RAW MOTOR ENFORCEMENT:
 * - Structured proprioception is exposed with explicit source attribution.
 * - Raw physical motor primitives: set_look, mouse_move, mouse_down, mouse_up, key_down, key_up, tick.
 * - Prismarine 3D First-Person Viewer rendered on port 3007.
 * - HTTP endpoint GET /viewscreen.jpg for instantaneous visual frame sampling.
 */

const http = require('http');

let mineflayer;
let viewerPkg;
let puppeteer;

try { mineflayer = require('mineflayer'); } catch (e) { mineflayer = null; }
try { viewerPkg = require('prismarine-viewer').mineflayer; } catch (e) { viewerPkg = null; }
try { puppeteer = require('puppeteer-core'); } catch (e) { puppeteer = null; }

let bot = null;
let viewerStarted = false;
let currentLook = { yaw: 0, pitch: 0 };
let heldButtons = new Set();
let currentDiggingBlock = null;
let inputLeaseTimer = null;

function releaseInputs() {
  clearTimeout(inputLeaseTimer);
  heldButtons.clear();
  currentDiggingBlock = null;
  if (!bot) return;
  bot.clearControlStates();
  if (bot.targetDigBlock) bot.stopDigging();
  bot.deactivateItem();
}

function renewInputLease() {
  clearTimeout(inputLeaseTimer);
  // A lost client cannot leave movement or mining held indefinitely.
  inputLeaseTimer = setTimeout(releaseInputs, 2000);
}

let browserInstance = null;
let pageInstance = null;

async function initHeadlessViewer() {
  if (!puppeteer) return;
  try {
    if (browserInstance) {
      try { await browserInstance.close(); } catch (e) {}
    }
    browserInstance = await puppeteer.launch({
      executablePath: 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
      headless: true,
      args: ['--no-sandbox', '--disable-setuid-sandbox', '--use-gl=angle', '--use-angle=d3d11']
    });
    pageInstance = await browserInstance.newPage();
    await pageInstance.setViewport({ width: 640, height: 480 });
    await pageInstance.goto('http://localhost:3007', { waitUntil: 'networkidle0', timeout: 15000 });
    console.log('[HeadlessStreamer] Visual frame pipeline ready on http://127.0.0.1:3000/viewscreen.jpg');
    updateVisualHotbar();
  } catch (err) {
    console.error('[HeadlessStreamer Error]:', err.message);
  }
}

function updateVisualHotbar() {
  if (!pageInstance || !bot || !bot.inventory) return;
  try {
    const hotbarData = [];
    for (let i = 0; i < 9; i++) {
      const item = bot.inventory.slots[36 + i];
      hotbarData.push(item ? { name: item.name, count: item.count } : null);
    }
    pageInstance.evaluate((items) => {
      items.forEach((item, idx) => {
        const slotEl = document.getElementById(`slot-${idx}`);
        if (slotEl) {
          if (item) {
            slotEl.innerHTML = `<span style="font-size:10px;font-weight:bold;color:#f1c40f;text-shadow:1px 1px #000;text-align:center;line-height:1.1;display:block;">${item.name.replace(/_/g, ' ').slice(0, 5)}<br><span style="font-size:11px;color:#fff">${item.count}</span></span>`;
            slotEl.style.position = 'relative';
          } else {
            slotEl.innerHTML = '';
          }
        }
      });
    }, hotbarData).catch(() => {});
  } catch (e) {}
}

function getBotState() {
  if (!bot || !bot.entity) {
    return { connected: false, source: 'mineflayer' };
  }
  // These values come from Mineflayer's live bot state, not image inference.
  let inventory = null;
  if (bot.inventory && Array.isArray(bot.inventory.slots)) {
    inventory = {};
    for (const item of bot.inventory.slots) {
      if (item && item.name) inventory[item.name] = (inventory[item.name] || 0) + item.count;
    }
  }
  return {
    connected: true,
    source: 'mineflayer_live_state',
    observed_at: Date.now() / 1000,
    username: bot.username,
    yaw: (bot.entity.yaw * 180 / Math.PI) % 360,
    pitch: (bot.entity.pitch * 180 / Math.PI),
    health: Number.isFinite(bot.health) ? bot.health : null,
    food: Number.isFinite(bot.food) ? bot.food : null,
    position: bot.entity.position ? {
      x: bot.entity.position.x, y: bot.entity.position.y, z: bot.entity.position.z
    } : null,
    inventory,
    held_item: bot.heldItem ? bot.heldItem.name : null,
    sheltered: null
  };
}

function parseJsonBody(req) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', chunk => { body += chunk; });
    req.on('end', () => {
      if (!body) return resolve({});
      try {
        resolve(JSON.parse(body));
      } catch (err) {
        reject(err);
      }
    });
  });
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);
  const pathname = url.pathname;

  const sendJson = (code, data) => {
    res.setHeader('Content-Type', 'application/json');
    res.writeHead(code);
    res.end(JSON.stringify(data));
  };

  try {
    // 1. VISUAL SENSOR ENDPOINT: GET /viewscreen.jpg
    if (req.method === 'GET' && (pathname === '/viewscreen.jpg' || pathname === '/viewscreen.png')) {
      if (!pageInstance) {
        res.writeHead(503, { 'Content-Type': 'text/plain' });
        return res.end('Viewscreen streamer not initialized or connecting');
      }
      try {
        const isPng = pathname.endsWith('.png');
        const buf = await pageInstance.screenshot({
          type: isPng ? 'png' : 'jpeg',
          quality: isPng ? undefined : 75
        });
        res.writeHead(200, {
          'Content-Type': isPng ? 'image/png' : 'image/jpeg',
          'Content-Length': buf.length,
          'Cache-Control': 'no-cache, no-store, must-revalidate'
        });
        return res.end(buf);
      } catch (e) {
        res.writeHead(500, { 'Content-Type': 'text/plain' });
        return res.end('Error capturing viewscreen frame: ' + e.message);
      }
    }

    // 2. RELOAD ENDPOINT
    if (req.method === 'GET' && pathname === '/reload') {
      if (pageInstance) {
        await pageInstance.reload({ waitUntil: 'networkidle0' });
        return sendJson(200, { status: 'reloaded' });
      }
      return sendJson(400, { error: 'pageInstance not running' });
    }

    // 3. STATUS ENDPOINT
    if (req.method === 'GET' && pathname === '/status') {
      return sendJson(200, {
        mineflayerAvailable: !!mineflayer,
        connected: !!(bot && bot.entity),
        viewerActive: viewerStarted,
        streamerActive: !!pageInstance,
        state: getBotState()
      });
    }

    if (req.method === 'GET' && pathname === '/state') {
      return sendJson(200, getBotState());
    }

    // 3. CONNECT ENDPOINT
    if (req.method === 'POST' && pathname === '/connect') {
      if (!mineflayer) {
        return sendJson(500, { error: 'mineflayer dependency not installed' });
      }
      const body = await parseJsonBody(req);
      const host = body.host || 'localhost';
      const port = body.port || 25565;
      const username = body.username || 'ReticleAgent';
      const version = body.version || '1.21.4';

      if (bot) {
        try { bot.quit(); } catch(e) {}
        bot = null;
      }

      console.log(`[Connecting] host=${host}, port=${port}, username=${username}, version=${version}`);
      bot = mineflayer.createBot({
        host,
        port: parseInt(port),
        username,
        version
      });

      bot.on('login', () => {
        console.log(`[Bot Logged In]: ${bot.username}`);
      });

      bot.on('spawn', () => {
        console.log(`[Bot Spawned]: ${bot.username}`);
        bot.inventory.on('windowUpdate', updateVisualHotbar);
        bot.inventory.on('updateSlot', updateVisualHotbar);
        if (viewerPkg && !viewerStarted) {
          viewerStarted = true;
          try {
            viewerPkg(bot, { port: 3007, firstPerson: true, viewDistance: 6 });
            console.log('[PrismarineViewer] 3D First-Person Viewscreen active at http://localhost:3007');
            // Give server 1 second to start, then connect headless streamer
            setTimeout(() => {
              initHeadlessViewer();
            }, 1000);
          } catch (err) {
            console.error('[PrismarineViewer Error]:', err.message);
          }
        }
      });

      bot.on('error', (err) => {
        console.error('[Bot Error]:', err.message);
      });

      return sendJson(200, { status: 'connecting', host, port, username });
    }

    // 4. DISCONNECT ENDPOINT
    if (req.method === 'POST' && pathname === '/disconnect') {
      if (pageInstance) {
        try { await browserInstance.close(); } catch(e) {}
        pageInstance = null;
        browserInstance = null;
      }
      if (bot) {
        bot.quit();
        bot = null;
      }
      return sendJson(200, { status: 'disconnected' });
    }

    // 5. REJECT ORACLE PROBES
    if (req.method === 'POST' && pathname === '/probe') {
      return sendJson(403, {
        error: 'Forbidden: Direct memory probes (inventory, health, entities) are disabled. Perception must be strictly visual via the viewscreen.'
      });
    }

    // 6. RAW MOTOR CONTROLS
    if (req.method === 'POST' && pathname === '/action') {
      if (!bot || !bot.entity) {
        return sendJson(400, { error: 'Bot is not connected' });
      }
      const body = await parseJsonBody(req);
      const type = body.action || body.type;
      const params = body.params || body;

      // set_look (yaw, pitch in degrees)
      if (type === 'set_look' || type === 'look') {
        const yaw = params.yaw !== undefined ? params.yaw : currentLook.yaw;
        const pitch = params.pitch !== undefined ? params.pitch : currentLook.pitch;
        currentLook = { yaw, pitch };
        await bot.look(yaw * (Math.PI / 180), pitch * (Math.PI / 180), true);
        return sendJson(200, { success: true, action: 'set_look', yaw, pitch });
      }

      // mouse_move (relative dx, dy)
      if (type === 'mouse_move') {
        const dx = params.dx || 0;
        const dy = params.dy || 0;
        const sensitivity = params.sensitivity || 0.15;
        let newYaw = (currentLook.yaw + dx * sensitivity) % 360;
        let newPitch = Math.max(-90, Math.min(90, currentLook.pitch + dy * sensitivity));
        currentLook = { yaw: newYaw, pitch: newPitch };
        await bot.look(newYaw * (Math.PI / 180), newPitch * (Math.PI / 180), true);
        return sendJson(200, { success: true, action: 'mouse_move', yaw: newYaw, pitch: newPitch });
      }

      // mouse_down (button: "left" | "right")
      if (type === 'mouse_down') {
        renewInputLease();
        const button = (params.button || 'left').toLowerCase();
        heldButtons.add(button);

        if (button === 'left') {
          const targetBlock = bot.blockAtCursor(4.5);
          if (targetBlock) {
            currentDiggingBlock = targetBlock;
            bot.dig(targetBlock, true).then(() => {
              currentDiggingBlock = null;
            }).catch(() => {
              currentDiggingBlock = null;
            });
            return sendJson(200, { success: true, action: 'mouse_down', button: 'left', target: targetBlock.name });
          } else {
            bot.swingArm('right');
            return sendJson(200, { success: true, action: 'mouse_down', button: 'left', target: 'air' });
          }
        } else if (button === 'right') {
          bot.activateItem();
          return sendJson(200, { success: true, action: 'mouse_down', button: 'right' });
        }
        return sendJson(400, { error: `Unknown mouse button: ${button}` });
      }

      // mouse_up (button: "left" | "right")
      if (type === 'mouse_up') {
        const button = (params.button || 'left').toLowerCase();
        heldButtons.delete(button);

        if (button === 'left') {
          if (bot.targetDigBlock) {
            bot.stopDigging();
          }
          currentDiggingBlock = null;
          return sendJson(200, { success: true, action: 'mouse_up', button: 'left' });
        } else if (button === 'right') {
          bot.deactivateItem();
          return sendJson(200, { success: true, action: 'mouse_up', button: 'right' });
        }
        return sendJson(400, { error: `Unknown mouse button: ${button}` });
      }

      // key_down
      if (type === 'key_down') {
        const key = (params.key || '').toLowerCase();
        const keyMap = {
          'w': 'forward',
          's': 'back',
          'a': 'left',
          'd': 'right',
          'space': 'jump',
          'shift': 'sneak',
          'control': 'sprint'
        };

        if (keyMap[key]) {
          renewInputLease();
          bot.setControlState(keyMap[key], true);
          return sendJson(200, { success: true, action: 'key_down', key });
        } else if (/^[1-9]$/.test(key)) {
          const slotIdx = parseInt(key, 10) - 1;
          bot.setQuickBarSlot(slotIdx);
          if (pageInstance) {
            pageInstance.evaluate((idx) => {
              document.querySelectorAll('.hotbar-slot').forEach(el => el.classList.remove('active'));
              const target = document.getElementById(`slot-${idx}`);
              if (target) target.classList.add('active');
            }, slotIdx).catch(() => {});
          }
          return sendJson(200, { success: true, action: 'key_down', key, slot: slotIdx });
        }
        return sendJson(400, { error: `Unsupported key: ${key}` });
      }

      // key_up
      if (type === 'key_up') {
        const key = (params.key || '').toLowerCase();
        const keyMap = {
          'w': 'forward',
          's': 'back',
          'a': 'left',
          'd': 'right',
          'space': 'jump',
          'shift': 'sneak',
          'control': 'sprint'
        };

        if (keyMap[key]) {
          bot.setControlState(keyMap[key], false);
          return sendJson(200, { success: true, action: 'key_up', key });
        }
        return sendJson(200, { success: true, action: 'key_up', key });
      }

      // release_all: cancellation-safe spinal primitive
      if (type === 'release_all') {
        releaseInputs();
        return sendJson(200, { success: true, action: 'release_all' });
      }

      // tick (advance physics / wait)
      if (type === 'tick') {
        const ticks = Number(params.ticks ?? 1);
        if (!Number.isInteger(ticks) || ticks < 1 || ticks > 40) {
          return sendJson(400, { error: 'ticks must be an integer between 1 and 40' });
        }
        await new Promise(resolve => setTimeout(resolve, ticks * 50));
        return sendJson(200, { success: true, action: 'tick', ticks });
      }

      // craft (procedural crafting primitive)
      if (type === 'craft') {
        const recipeName = params.recipe;
        const count = params.count || params.quantity || 1;
        const item = bot.registry.itemsByName[recipeName];
        if (!item) {
          return sendJson(400, { error: `Unknown item for recipe: ${recipeName}` });
        }
        let craftingTable = null;
        if (params.crafting_table) {
          craftingTable = bot.findBlock({ matching: bot.registry.blocksByName['crafting_table']?.id, maxDistance: 4 });
        }
        const recipes = bot.recipesFor(item.id, null, 1, craftingTable);
        if (!recipes || recipes.length === 0) {
          return sendJson(400, { error: `No valid recipe found for ${recipeName} with current inventory` });
        }
        try {
          await bot.craft(recipes[0], count, craftingTable);
          try {
            await bot.equip(item.id, 'hand');
          } catch (e) {}
          // Sync visual HUD if pageInstance is live
          if (pageInstance) updateVisualHotbar();
          return sendJson(200, { success: true, action: 'craft', recipe: recipeName, count });
        } catch (craftErr) {
          return sendJson(500, { error: `Crafting failed: ${craftErr.message}` });
        }
      }

      // equip (equip an item from inventory into hand or armor)
      if (type === 'equip') {
        const itemName = params.item || params.name;
        const item = bot.registry.itemsByName[itemName];
        if (!item) {
          return sendJson(400, { error: `Unknown item: ${itemName}` });
        }
        try {
          await bot.equip(item.id, params.destination || 'hand');
          if (pageInstance) updateVisualHotbar();
          return sendJson(200, { success: true, action: 'equip', item: itemName });
        } catch (equipErr) {
          return sendJson(500, { error: `Equip failed: ${equipErr.message}` });
        }
      }

      // place_block (place held item against target block in cursor)
      if (type === 'place_block' || type === 'place') {
        const targetBlock = bot.blockAtCursor(4.5);
        if (!targetBlock) {
          return sendJson(400, { error: 'No block in cursor to place against' });
        }
        try {
          const Vec3 = require('vec3').Vec3;
          const face = params.face ? new Vec3(params.face[0], params.face[1], params.face[2]) : new Vec3(0, 1, 0);
          await bot.placeBlock(targetBlock, face);
          if (pageInstance) updateVisualHotbar();
          return sendJson(200, { success: true, action: 'place_block', target: targetBlock.name });
        } catch (err) {
          return sendJson(500, { error: `Place block failed: ${err.message}` });
        }
      }

      return sendJson(400, { error: `Unknown action: ${type}` });
    }

    sendJson(404, { error: 'Not found' });
  } catch (err) {
    sendJson(500, { error: err.message, stack: err.stack });
  }
});

const PORT = process.env.PORT || 3000;
server.listen(PORT, '127.0.0.1', () => {
  console.log(`[MineflayerBridge] Listening on http://127.0.0.1:${PORT}`);
});
