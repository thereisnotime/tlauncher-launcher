"""
Container management module for Minecraft Launcher.
Handles starting, stopping, and monitoring containers.
"""
import subprocess
import threading
from typing import Dict, Optional, Callable, Iterator
from .composer import build_compose_command


class ContainerManager:
    """Manages container lifecycle and operations."""

    def __init__(self, config: Dict[str, str]):
        """
        Initialize container manager.

        Args:
            config: Configuration dict with runtime, gpu, display, audio
        """
        self.config = config
        self.process: Optional[subprocess.Popen] = None
        self._stop_requested = False

    def start(self, detached: bool = False, force_recreate: bool = False,
              output_callback: Callable[[str], None] = None) -> bool:
        """
        Start the container.

        Args:
            detached: Run in detached mode (-d)
            force_recreate: Force recreate containers
            output_callback: Function to call with each line of output

        Returns:
            bool: True if started successfully
        """
        extra_args = []
        if detached:
            extra_args.append('-d')
        if force_recreate:
            extra_args.append('--force-recreate')

        cmd = build_compose_command(self.config, 'up', extra_args)

        try:
            if detached:
                # For detached mode, just run and return
                result = subprocess.run(cmd, capture_output=True, text=True)
                return result.returncode == 0
            else:
                # For interactive mode, stream output
                self.process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1
                )

                # Stream output lines
                if output_callback:
                    for line in iter(self.process.stdout.readline, ''):
                        if line:
                            output_callback(line.rstrip())
                        if self._stop_requested:
                            break

                # Wait for process to complete
                self.process.wait()
                return self.process.returncode == 0

        except Exception as e:
            if output_callback:
                output_callback(f"Error starting container: {str(e)}")
            return False

    def stop(self) -> bool:
        """
        Stop the container.

        Returns:
            bool: True if stopped successfully
        """
        self._stop_requested = True

        cmd = build_compose_command(self.config, 'down')

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            return False
        except Exception:
            return False

    def restart(self, output_callback: Callable[[str], None] = None) -> bool:
        """
        Restart the container.

        Args:
            output_callback: Function to call with output lines

        Returns:
            bool: True if restarted successfully
        """
        if output_callback:
            output_callback("Stopping container...")

        if not self.stop():
            if output_callback:
                output_callback("Failed to stop container")
            return False

        if output_callback:
            output_callback("Starting container...")

        return self.start(output_callback=output_callback)

    def logs(self, follow: bool = False, tail: int = None) -> Iterator[str]:
        """
        Get container logs.

        Args:
            follow: Follow log output (-f)
            tail: Number of lines from end to show

        Yields:
            str: Log lines
        """
        extra_args = []
        if follow:
            extra_args.append('-f')
        if tail:
            extra_args.extend(['--tail', str(tail)])

        cmd = build_compose_command(self.config, 'logs', extra_args)

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )

            for line in iter(process.stdout.readline, ''):
                if line:
                    yield line.rstrip()

        except Exception as e:
            yield f"Error reading logs: {str(e)}"

    def status(self) -> Dict[str, any]:
        """
        Get container status.

        Returns:
            dict: Status information with keys: running, containers
        """
        cmd = build_compose_command(self.config, 'ps', ['--format', 'json'])

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

            if result.returncode == 0:
                # Parse output to determine if container is running
                output = result.stdout.strip()
                running = bool(output and 'tlauncher' in output.lower())

                return {
                    'running': running,
                    'output': output
                }
            else:
                return {
                    'running': False,
                    'error': result.stderr
                }

        except subprocess.TimeoutExpired:
            return {
                'running': False,
                'error': 'Status check timed out'
            }
        except Exception as e:
            return {
                'running': False,
                'error': str(e)
            }

    def is_running(self) -> bool:
        """
        Quick check if container is running.

        Returns:
            bool: True if running
        """
        status = self.status()
        return status.get('running', False)


def start_container_async(config: Dict[str, str],
                           detached: bool = False,
                           output_callback: Callable[[str], None] = None,
                           completion_callback: Callable[[bool], None] = None):
    """
    Start container in a background thread (for GUI).

    Args:
        config: Configuration dict
        detached: Run in detached mode
        output_callback: Function to call with output lines
        completion_callback: Function to call when complete with success status
    """
    def _worker():
        manager = ContainerManager(config)
        success = manager.start(detached=detached, output_callback=output_callback)
        if completion_callback:
            completion_callback(success)

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    return thread
