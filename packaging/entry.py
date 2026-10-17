# Script d'entrée pour PyInstaller : un import absolu, que le paquet gelé sait
# résoudre (contrairement à naosnatcher/__main__.py et ses imports relatifs).
from naosnatcher.launcher import main

main()
