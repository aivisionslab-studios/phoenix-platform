import fs from 'node:fs';

let failed = 0;
const check = (name, ok) => {
  console.log(`${ok ? 'PASS' : 'FAIL'} ${name}`);
  if (!ok) failed++;
};

const src = fs.readFileSync(new URL('./src/components/aviary/AviaryApp.tsx', import.meta.url), 'utf8');
check('inventário de disco possui estado React próprio', src.includes('const [diskChatModels, setDiskChatModels] = useState<string[]>([])'));
check('scan autoritativo atualiza ref e estado de inventário', src.includes('setDiskChatModels(trackedData.diskChatModels)'));
check('availableModels une provider + inventário de disco', src.includes('...p.models, ...diskChatModels'));
check('llama instalado continua visível mesmo offline/disconnected', src.includes("p.type === 'llama-server' && providerModels.length > 0"));
check('memo depende do inventário de disco', src.includes('}, [providers, diskChatModels]);'));

if (failed) process.exit(1);
