import asyncio
import logging
from typing import List
from phoenix_kernel.runtime.contracts.model_contracts import GenerationFailed

logger = logging.getLogger(__name__)

class SubprocessExecutor:
    @staticmethod
    async def run(cmd: List[str], timeout: int) -> tuple[bool, str]:
        logger.info(f"Executor running: {' '.join(cmd)}")
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            if process.returncode == 0:
                return True, "Success"
            else:
                raise GenerationFailed(f"Process exited {process.returncode}. stderr: {stderr.decode()[-500:]}")
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise GenerationFailed(f"Timeout ({timeout}s) reached.")
