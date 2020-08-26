# Copyright (C) 2020 FireEye, Inc. All Rights Reserved.

import speakeasy.winenv.arch as _arch
import speakeasy.winenv.defs.registry.reg as regdefs
import speakeasy.winenv.defs.windows.windows as windefs

import speakeasy.winenv.defs.windows.kernel32 as k32
import speakeasy.winenv.defs.windows.advapi32 as adv32
import speakeasy.windows.objman as objman

from .. import api
import hashlib


class AdvApi32(api.ApiHandler):
    """
    Implements exported functions from advapi32.dll
    """

    name = 'advapi32'
    apihook = api.ApiHandler.apihook
    impdata = api.ApiHandler.impdata

    def __init__(self, emu):
        super(AdvApi32, self).__init__(emu)
        self.funcs = {}
        self.data = {}
        self.hash_objects = {}
        self.key_objects = {}
        self.k32types = k32
        self.win = adv32
        self.curr_rand = 0
        self.curr_handle = 0x2800

        super(AdvApi32, self).__get_hook_attrs__(self)

    def get_handle(self):
        self.curr_handle += 4
        return self.curr_handle

    @apihook('RegOpenKey', argc=3, conv=_arch.CALL_CONV_STDCALL)
    def RegOpenKey(self, emu, argv, ctx={}):
        '''
        LSTATUS RegOpenKeyA(
          HKEY   hKey,
          LPCSTR lpSubKey,
          PHKEY  phkResult
        );
        '''

        hKey, lpSubKey, phkResult = argv
        rv = windefs.ERROR_SUCCESS
        hnd = 0

        hkey_name = regdefs.get_hkey_type(hKey)
        if hkey_name:
            argv[0] = hkey_name
            if not hnd and not lpSubKey:
                hnd = hKey
        else:
            key_obj = emu.regman.get_key_from_handle(hKey)
            hkey_name = key_obj.path

        cw = self.get_char_width(ctx)
        if lpSubKey:
            lpSubKey = self.read_mem_string(lpSubKey, cw)
            argv[1] = lpSubKey

            if hkey_name and lpSubKey:
                if not lpSubKey.startswith('\\'):
                    lpSubKey = '\\' + lpSubKey
                lpSubKey = hkey_name + lpSubKey

            hnd = self.reg_open_key(lpSubKey, create=True)
            if not hnd:
                rv = windefs.ERROR_PATH_NOT_FOUND

            self.log_registry_access(lpSubKey, 'open_key', handle=hnd)

        if phkResult and hnd:
            self.mem_write(phkResult, hnd.to_bytes(self.get_ptr_size(), 'little'))

        return rv

    @apihook('RegOpenKeyEx', argc=5, conv=_arch.CALL_CONV_STDCALL)
    def RegOpenKeyEx(self, emu, argv, ctx={}):
        '''
        LSTATUS RegOpenKeyEx(
          HKEY   hKey,
          LPTSTR lpSubKey,
          DWORD  ulOptions,
          REGSAM samDesired,
          PHKEY  phkResult
        );
        '''

        hKey, lpSubKey, ulOptions, samDesired, phkResult = argv
        rv = windefs.ERROR_SUCCESS

        hnd = 0

        hkey_name = regdefs.get_hkey_type(hKey)
        if hkey_name:
            argv[0] = hkey_name
            if not hnd and not lpSubKey:
                hnd = hKey

        cw = self.get_char_width(ctx)
        if lpSubKey:
            lpSubKey = self.read_mem_string(lpSubKey, cw)
            argv[1] = lpSubKey

            if hkey_name and lpSubKey:
                if not lpSubKey.startswith('\\'):
                    lpSubKey = '\\' + lpSubKey
                lpSubKey = hkey_name + lpSubKey

            hnd = self.reg_open_key(lpSubKey, create=True)
            if not hnd:
                rv = windefs.ERROR_PATH_NOT_FOUND

            self.log_registry_access(lpSubKey, 'open_key', handle=hnd)

        if phkResult and hnd:
            self.mem_write(phkResult, hnd.to_bytes(self.get_ptr_size(), 'little'))

        return rv

    @apihook('RegQueryValueEx', argc=6, conv=_arch.CALL_CONV_STDCALL)
    def RegQueryValueEx(self, emu, argv, ctx={}):
        '''
        LSTATUS RegQueryValueEx(
          HKEY    hKey,
          LPTSTR  lpValueName,
          LPDWORD lpReserved,
          LPDWORD lpType,
          LPBYTE  lpData,
          LPDWORD lpcbData
        );
        '''

        hKey, lpValueName, lpReserved, lpType, lpData, lpcbData = argv
        rv = windefs.ERROR_SUCCESS

        cw = self.get_char_width(ctx)
        if lpValueName:
            lpValueName = self.read_mem_string(lpValueName, cw)
            argv[1] = lpValueName

        type_name = regdefs.get_value_type(lpType)
        if type_name:
            argv[3] = type_name

        length = 0
        if lpcbData:
            length = self.mem_read(lpcbData, 4)
            length = int.from_bytes(length, 'little')
            argv[5] = length

        key = self.reg_get_key(hKey)
        if key:
            val = key.get_value(lpValueName)
            if val:
                output = b''

                if lpcbData:
                    self.mem_write(lpcbData, len(output).to_bytes(4, 'little'))

                if len(output) > length:
                    rv = windefs.ERROR_INSUFFICIENT_BUFFER
                else:
                    if lpData:
                        self.mem_write(lpData, output)

            # For now, return an empty buffer
            else:
                output = b'\x00' * length
                if lpData:
                    try:
                        self.mem_write(lpData, output)
                    except Exception:
                        return windefs.ERROR_INVALID_PARAMETER
                if lpcbData:
                    self.mem_write(lpcbData, len(output).to_bytes(4, 'little'))
                rv = windefs.ERROR_SUCCESS

            kp = key.get_path()
            self.log_registry_access(kp, 'read_value', value_name=lpValueName, size=length,
                                     buffer=lpData)

        return rv

    @apihook('RegCloseKey', argc=1, conv=_arch.CALL_CONV_STDCALL)
    def RegCloseKey(self, emu, argv, ctx={}):
        '''
        LSTATUS RegCloseKey(
          HKEY hKey
        );
        '''

        hKey, = argv
        rv = windefs.ERROR_SUCCESS

        key = self.reg_get_key(hKey)
        if not key:
            rv = windefs.ERROR_INVALID_HANDLE

        return rv

    @apihook('RegEnumKey', argc=4, conv=_arch.CALL_CONV_STDCALL)
    def RegEnumKey(self, emu, argv, ctx={}):
        '''
        LSTATUS RegEnumKey(
          HKEY  hKey,
          DWORD dwIndex,
          LPTSTR lpName,
          DWORD cchName
        );
        '''

        hKey, dwIndex, lpName, cchName = argv

        cw = self.get_char_width(ctx)

        rv = windefs.ERROR_INVALID_HANDLE
        if hKey:
            key = self.reg_get_key(hKey)
            argv[0] = key.get_path()
            if not key:
                rv = windefs.ERROR_INVALID_HANDLE
            else:
                subkeys = self.reg_get_subkeys(key)
                if (dwIndex + 1) > len(subkeys):
                    rv = windefs.ERROR_NO_MORE_ITEMS
                else:
                    if lpName:
                        sk = subkeys[dwIndex]
                        name = sk.get_path()
                        if cw == 2:
                            name = name.encode('utf-16le')
                        else:
                            name = name.encode('utf-8')
                        self.mem_write(lpName, name)
                        rv = windefs.ERROR_SUCCESS

        return rv

    @apihook('RegQueryInfoKey', argc=12, conv=_arch.CALL_CONV_STDCALL)
    def RegQueryInfoKey(self, emu, argv, ctx={}):
        # TODO: stub
        '''
        LSTATUS RegQueryInfoKeyA(
          HKEY      hKey,
          LPSTR     lpClass,
          LPDWORD   lpcchClass,
          LPDWORD   lpReserved,
          LPDWORD   lpcSubKeys,
          LPDWORD   lpcbMaxSubKeyLen,
          LPDWORD   lpcbMaxClassLen,
          LPDWORD   lpcValues,
          LPDWORD   lpcbMaxValueNameLen,
          LPDWORD   lpcbMaxValueLen,
          LPDWORD   lpcbSecurityDescriptor,
          PFILETIME lpftLastWriteTime
        );
        '''

        hKey, lpClass, lpcchClass, _, subkeys, max_subkey_len, max_class_len, \
            values, max_value_name_len, max_value_len, sec_desc, last_write = argv

        rv = windefs.ERROR_SUCCESS

        hkey_name = regdefs.get_hkey_type(hKey)
        if hkey_name:
            argv[0] = hkey_name

        key = self.reg_get_key(hKey)
        if not key:
            rv = windefs.ERROR_INVALID_HANDLE

        return rv

    @apihook('OpenProcessToken', argc=3, conv=_arch.CALL_CONV_STDCALL)
    def OpenProcessToken(self, emu, argv, ctx={}):
        '''
        BOOL OpenProcessToken(
          HANDLE  ProcessHandle,
          DWORD   DesiredAccess,
          PHANDLE pTokenHandle
        );
        '''

        hProcess, DesiredAccess, pTokenHandle = argv
        rv = 0

        if hProcess == self.get_max_int():
            obj = emu.get_current_process()
        else:
            obj = self.get_object_from_handle(hProcess)

        if obj:
            token = obj.get_token()
            hToken = token.get_handle()

            if pTokenHandle:
                hnd = (hToken).to_bytes(self.get_ptr_size(), 'little')
                self.mem_write(pTokenHandle, hnd)
                rv = 1
                emu.set_last_error(windefs.ERROR_SUCCESS)
            else:
                emu.set_last_error(windefs.ERROR_INVALID_PARAMETER)

        return rv

    @apihook('OpenThreadToken', argc=4, conv=_arch.CALL_CONV_STDCALL)
    def OpenThreadToken(self, emu, argv, ctx={}):
        '''
        BOOL OpenThreadToken(
            HANDLE  ThreadHandle,
            DWORD   DesiredAccess,
            BOOL    OpenAsSelf,
            PHANDLE TokenHandle
        );
        '''

        ThreadHandle, DesiredAccess, OpenAsSelf, pTokenHandle = argv
        rv = 0

        if ThreadHandle == self.get_max_int():
            obj = emu.get_current_thread()
        else:
            obj = self.get_object_from_handle(ThreadHandle)

        if obj:
            token = obj.get_token()
            hToken = token.get_handle()

            if pTokenHandle:
                hnd = (hToken).to_bytes(self.get_ptr_size(), 'little')
                self.mem_write(pTokenHandle, hnd)
                rv = 1
                emu.set_last_error(windefs.ERROR_SUCCESS)
            else:
                emu.set_last_error(windefs.ERROR_INVALID_PARAMETER)

        return rv

    @apihook('DuplicateTokenEx', argc=6, conv=_arch.CALL_CONV_STDCALL)
    def DuplicateTokenEx(self, emu, argv, ctx={}):
        '''
        BOOL DuplicateTokenEx(
          HANDLE                       hExistingToken,
          DWORD                        dwDesiredAccess,
          LPSECURITY_ATTRIBUTES        lpTokenAttributes,
          SECURITY_IMPERSONATION_LEVEL ImpersonationLevel,
          TOKEN_TYPE                   TokenType,
          PHANDLE                      phNewToken
        );
        '''

        (hExistingToken, access, token_attrs, imp_level, toktype,
         phNewToken) = argv
        rv = 0

        obj = self.get_object_from_handle(hExistingToken)

        if obj:

            new_token = emu.new_object(objman.Token)
            hnd_new_token = new_token.get_handle()

            if phNewToken:
                hnd = (hnd_new_token).to_bytes(self.get_ptr_size(), 'little')
                self.mem_write(phNewToken, hnd)
                rv = 1
                emu.set_last_error(windefs.ERROR_SUCCESS)
            else:
                emu.set_last_error(windefs.ERROR_INVALID_PARAMETER)

        return rv

    @apihook('SetTokenInformation', argc=4, conv=_arch.CALL_CONV_STDCALL)
    def SetTokenInformation(self, emu, argv, ctx={}):
        '''
        BOOL SetTokenInformation(
          HANDLE                  TokenHandle,
          TOKEN_INFORMATION_CLASS TokenInformationClass,
          LPVOID                  TokenInformation,
          DWORD                   TokenInformationLength
        );
        '''

        handle, info_class, info, info_len = argv

        rv = 1

        return rv

    @apihook('StartServiceCtrlDispatcher', argc=1)
    def StartServiceCtrlDispatcher(self, emu, argv, ctx={}):
        '''
        BOOL StartServiceCtrlDispatcher(
          const SERVICE_TABLE_ENTRY *lpServiceStartTable
        );
        '''
        lpServiceStartTable, = argv

        cw = self.get_char_width(ctx)

        ste = self.win.SERVICE_TABLE_ENTRY(emu.get_ptr_size())
        entry = self.mem_cast(ste, lpServiceStartTable)

        # Get the service name
        name = self.read_mem_string(entry.lpServiceName, cw) # noqa
        rv = True
        emu.set_last_error(windefs.ERROR_SUCCESS)

        return rv

    @apihook('OpenSCManager', argc=3)
    def OpenSCManager(self, emu, argv, ctx={}):
        '''
        SC_HANDLE OpenSCManager(
          LPCSTR lpMachineName,
          LPCSTR lpDatabaseName,
          DWORD  dwDesiredAccess
        );
        '''
        lpMachineName, lpDatabaseName, dwDesiredAccess = argv

        hScm = self.mem_alloc(size=8)
        emu.set_last_error(windefs.ERROR_SUCCESS)

        return hScm

    @apihook('CreateService', argc=13)
    def CreateService(self, emu, argv, ctx={}):
        '''
        SC_HANDLE CreateServiceA(
          SC_HANDLE hSCManager,
          LPCSTR    lpServiceName,
          LPCSTR    lpDisplayName,
          DWORD     dwDesiredAccess,
          DWORD     dwServiceType,
          DWORD     dwStartType,
          DWORD     dwErrorControl,
          LPCSTR    lpBinaryPathName,
          LPCSTR    lpLoadOrderGroup,
          LPDWORD   lpdwTagId,
          LPCSTR    lpDependencies,
          LPCSTR    lpServiceStartName,
          LPCSTR    lpPassword
        );
        '''
        (hScm, svc_name, disp_name, access,
         svc_type, start_type, error_ctrl, bin_path,
         load_group, tag_id, deps, svc_start_name,
         password) = argv

        cw = self.get_char_width(ctx)

        if svc_name:
            _sname = self.read_mem_string(svc_name, cw)
            argv[1] = _sname
        if disp_name:
            _dname = self.read_mem_string(disp_name, cw)
            argv[2] = _dname
        if bin_path:
            _bpname = self.read_mem_string(bin_path, cw)
            argv[7] = _bpname

        hSvc = self.mem_alloc(size=8)
        emu.set_last_error(windefs.ERROR_SUCCESS)

        return hSvc

    @apihook('StartService', argc=3)
    def StartService(self, emu, argv, ctx={}):
        '''
        BOOL StartService(
          SC_HANDLE hService,
          DWORD     dwNumServiceArgs,
          LPCSTR    *lpServiceArgVectors
        );
        '''
        hService, dwNumServiceArgs, lpServiceArgVectors = argv

        rv = 1

        emu.set_last_error(windefs.ERROR_SUCCESS)

        return rv

    @apihook('CloseServiceHandle', argc=1)
    def CloseServiceHandle(self, emu, argv, ctx={}):
        '''
        BOOL CloseServiceHandle(
          SC_HANDLE hSCObject
        );
        '''
        CloseServiceHandle, = argv

        self.mem_free(CloseServiceHandle)

        rv = 1

        emu.set_last_error(windefs.ERROR_SUCCESS)

        return rv

    @apihook('ChangeServiceConfig2', argc=3)
    def ChangeServiceConfig2(self, emu, argv, ctx={}):
        '''
        BOOL ChangeServiceConfig2(
          SC_HANDLE hService,
          DWORD     dwInfoLevel,
          LPVOID    lpInfo
        );
        '''
        hService, dwInfoLevel, lpInfo = argv

        rv = 1

        emu.set_last_error(windefs.ERROR_SUCCESS)

        return rv

    @apihook('CryptAcquireContext', argc=5)
    def CryptAcquireContext(self, emu, argv, ctx={}):
        '''
        BOOL CryptAcquireContext(
            HCRYPTPROV *phProv,
            LPCSTR     szContainer,
            LPCSTR     szProvider,
            DWORD      dwProvType,
            DWORD      dwFlags
        );
        '''
        phProv, szContainer, szProvider, dwProvType, dwFlags = argv
        cont_str, prov_str = '', ''
        cw = self.get_char_width(ctx)
        rv = False

        if szContainer:
            cont_str = self.read_mem_string(szContainer, cw)
            argv[1] = cont_str
        if szProvider:
            prov_str = self.read_mem_string(szProvider, cw)
            argv[2] = prov_str

        cm = emu.get_crypt_manager()
        hnd = cm.crypt_open(cont_str, prov_str, dwProvType, dwFlags)

        if hnd and phProv:
            self.mem_write(phProv, hnd.to_bytes(emu.get_ptr_size(), 'little'))
            rv = True
            emu.set_last_error(windefs.ERROR_SUCCESS)

        return rv

    @apihook('CryptGenRandom', argc=3)
    def CryptGenRandom(self, emu, argv, ctx={}):
        '''
        BOOL CryptGenRandom(
            HCRYPTPROV hProv,
            DWORD      dwLen,
            BYTE       *pbBuffer
        );
        '''
        hProv, dwLen, pbBuffer = argv
        rv = False

        if pbBuffer:
            out = b'A' * dwLen
            self.mem_write(pbBuffer, out)
            rv = True

        return rv

    @apihook('AllocateAndInitializeSid', argc=11)
    def AllocateAndInitializeSid(self, emu, argv, ctx={}):
        '''
        BOOL AllocateAndInitializeSid(
            PSID_IDENTIFIER_AUTHORITY pIdentifierAuthority,
            BYTE                      nSubAuthorityCount,
            DWORD                     nSubAuthority0,
            DWORD                     nSubAuthority1,
            DWORD                     nSubAuthority2,
            DWORD                     nSubAuthority3,
            DWORD                     nSubAuthority4,
            DWORD                     nSubAuthority5,
            DWORD                     nSubAuthority6,
            DWORD                     nSubAuthority7,
            PSID                      *pSid
        );
        '''
        auth, count, sa0, sa1, sa2, sa3, sa4, sa5, sa6, sa7, pSid = argv
        rv = False

        if pSid:
            sid = self.mem_alloc(0x100, tag='api.struct.SID')
            self.mem_write(pSid, sid.to_bytes(emu.get_ptr_size(), 'little'))
            rv = True

        return rv

    @apihook('CheckTokenMembership', argc=3)
    def CheckTokenMembership(self, emu, argv, ctx={}):
        '''
        BOOL CheckTokenMembership(
            HANDLE TokenHandle,
            PSID   SidToCheck,
            PBOOL  IsMember
        );
        '''
        TokenHandle, SidToCheck, IsMember = argv
        rv = False

        if IsMember:
            self.mem_write(IsMember, (1).to_bytes(4, 'little'))
            rv = True
        return rv

    @apihook('FreeSid', argc=1)
    def FreeSid(self, emu, argv, ctx={}):
        '''
        PVOID FreeSid(
            PSID pSid
        );
        '''
        pSid,  = argv
        rv = pSid

        if pSid:
            self.mem_free(pSid)
            rv = 0
        return rv

    @apihook('CryptReleaseContext', argc=2)
    def CryptReleaseContext(self, emu, argv, ctx={}):
        '''
        BOOL CryptReleaseContext(
            HCRYPTPROV hProv,
            DWORD      dwFlags
        );
        '''
        hProv, dwFlags = argv
        rv = True

        cm = emu.get_crypt_manager()
        cm.crypt_close(hProv)

        return rv

    @apihook('GetUserName', argc=2)
    def GetUserName(self, emu, argv, ctx={}):
        '''
        BOOL GetUserName(
            LPSTR   lpBuffer,
            LPDWORD pcbBuffer
        );
        '''
        lpBuffer, pcbBuffer = argv
        rv = False
        cw = self.get_char_width(ctx)

        user = emu.get_user()
        user_name = user.get('name')

        if lpBuffer:
            if cw == 2:
                out = user_name.encode('utf-16le')
            elif cw == 1:
                out = user_name.encode('utf-8')
            self.mem_write(lpBuffer, out)
            rv = True
        if pcbBuffer:
            self.mem_write(pcbBuffer, (len(user_name)).to_bytes(4, 'little'))

        return rv

    @apihook('LookupPrivilegeValue', argc=3)
    def LookupPrivilegeValue(self, emu, argv, ctx={}):
        '''
        BOOL LookupPrivilegeValue(
            LPCSTR lpSystemName,
            LPCSTR lpName,
            PLUID  lpLuid
        );
        '''
        sysname, name, luid = argv
        rv = False
        cw = self.get_char_width(ctx)

        if sysname:
            sysname = self.read_mem_string(sysname, cw)
            argv[0] = sysname
        if name:
            name = self.read_mem_string(name, cw)
            argv[1] = name
            rv = True

        return rv

    @apihook('AdjustTokenPrivileges', argc=6)
    def AdjustTokenPrivileges(self, emu, argv, ctx={}):
        '''
        BOOL AdjustTokenPrivileges(
            HANDLE            TokenHandle,
            BOOL              DisableAllPrivileges,
            PTOKEN_PRIVILEGES NewState,
            DWORD             BufferLength,
            PTOKEN_PRIVILEGES PreviousState,
            PDWORD            ReturnLength
        );
        '''
        rv = True

        return rv

    @apihook('GetTokenInformation', argc=5)
    def GetTokenInformation(self, emu, argv, ctx={}):
        '''
        BOOL GetTokenInformation(
            HANDLE                  TokenHandle,
            TOKEN_INFORMATION_CLASS TokenInformationClass,
            LPVOID                  TokenInformation,
            DWORD                   TokenInformationLength,
            PDWORD                  ReturnLength
        );
        '''
        hnd, info_class, info, info_len, ret_len = argv
        rv = True

        if not info_len:
            rv = False
            emu.set_last_error(windefs.ERROR_INSUFFICIENT_BUFFER)

        if ret_len:
            self.mem_write(ret_len, (4).to_bytes(4, 'little'))

        return rv

    @apihook('CreateProcessAsUser', argc=11, conv=_arch.CALL_CONV_STDCALL)
    def CreateProcessAsUser(self, emu, argv, ctx={}):
        '''
        BOOL CreateProcessAsUser(
          HANDLE                hToken,
          LPCSTR                lpApplicationName,
          LPSTR                 lpCommandLine,
          LPSECURITY_ATTRIBUTES lpProcessAttributes,
          LPSECURITY_ATTRIBUTES lpThreadAttributes,
          BOOL                  bInheritHandles,
          DWORD                 dwCreationFlags,
          LPVOID                lpEnvironment,
          LPCSTR                lpCurrentDirectory,
          LPSTARTUPINFOA        lpStartupInfo,
          LPPROCESS_INFORMATION lpProcessInformation
        );
        '''
        token, app, cmd, pa, ta, inherit, flags, env, cd, si, ppi = argv

        cw = self.get_char_width(ctx)
        cmdstr = ''
        appstr = ''
        if app:
            appstr = self.read_mem_string(app, cw)
            argv[1] = appstr
        if cmd:
            cmdstr = self.read_mem_string(cmd, cw)
            if not appstr:
                appstr = cmdstr.split(' ')[0]
            argv[2] = cmdstr

        proc = emu.create_process(path=appstr, cmdline=cmdstr)
        proc_hnd = self.get_object_handle(proc)

        thread = proc.threads[0]
        thread_hnd = self.get_object_handle(thread)

        _pi = self.k32types.PROCESS_INFORMATION(emu.get_ptr_size())
        data = self.mem_cast(_pi, ppi)
        _pi.hProcess = proc_hnd
        _pi.hThread = thread_hnd
        _pi.dwProcessId = proc.pid
        _pi.dwThreadId = thread.tid

        self.mem_write(ppi, self.get_bytes(data))

        rv = 1

        self.log_process_event(proc, 'create')
        return rv

    @apihook('CryptCreateHash', argc=5)
    def CryptCreateHash(self, emu, argv, ctx={}):
        '''
        BOOL CryptCreateHash(
          HCRYPTPROV hProv,
          ALG_ID     Algid,
          HCRYPTKEY  hKey,
          DWORD      dwFlags,
          HCRYPTHASH *phHash
        );
        '''

        hash_algs = {
            0x00008004: ('CALG_SHA1', hashlib.sha1),
            0x0000800c: ('CALG_SHA_256', hashlib.sha256),
            0x0000800d: ('CALG_SHA_384', hashlib.sha384),
            0x0000800e: ('CALG_SHA_512', hashlib.sha512),
            0x00008003: ('CALG_MD5', hashlib.md5)
        }

        hProv, Algid, hKey, dwFlags, phHash = argv
        argv[1] = hash_algs.get(Algid, Algid)

        if hKey != 0:
            return 0

        if Algid not in hash_algs:
            emu.set_last_error(adv32.NTE_BAD_ALGID)
            return 0

        hnd = self.get_handle()
        self.hash_objects.update({hnd: hash_algs[Algid][1]()})
        self.mem_write(phHash, hnd.to_bytes(self.get_ptr_size(), 'little'))
        return 1

    @apihook('CryptHashData', argc=4)
    def CryptHashData(self, emu, argv, ctx={}):
        '''
        BOOL CryptHashData(
          HCRYPTHASH hHash,
          const BYTE *pbData,
          DWORD      dwDataLen,
          DWORD      dwFlags
        );
        '''

        hHash, pbData, dwDataLen, dwFlags = argv
        hnd = self.hash_objects.get(hHash, None)
        if hnd is None:
            emu.set_last_error(windefs.ERROR_INVALID_HANDLE)
            return 0

        if dwDataLen <= 0:
            return 0

        data = self.mem_read(pbData, dwDataLen)
        hnd.update(data)
        return 1

    @apihook('RegGetValueW', argc=7, conv=_arch.CALL_CONV_STDCALL)
    def RegGetValueW(self, emu, argv, ctx={}):
        '''
        LSTATUS RegGetValueW(
            HKEY    hkey,
            LPCWSTR lpSubKey,
            LPCWSTR lpValue,
            DWORD   dwFlags,
            LPDWORD pdwType,
            PVOID   pvData,
            LPDWORD pcbData
            );
        '''

        hKey, lpSubKey, lpValue, dwFlags, lpType, lpData, lpcbData = argv
        rv = windefs.ERROR_SUCCESS

        cw = self.get_char_width(ctx)
        if lpSubKey:
            lpSubKey = self.read_mem_string(lpSubKey, cw)
            argv[1] = lpSubKey

        if lpValue:
            lpValue = self.read_mem_string(lpValue, cw)
            argv[2] = lpValue

        type_name = regdefs.get_value_type(lpType)
        if type_name:
            argv[4] = type_name

        length = 0
        if lpcbData:
            length = self.mem_read(lpcbData, 4)
            length = int.from_bytes(length, 'little')

        key = self.reg_get_key(hKey)
        if key:
            val = key.get_value(lpValue)
            if val:
                output = b''

                if lpcbData:
                    self.mem_write(lpcbData, len(output).to_bytes(4, 'little'))

                if len(output) > length:
                    rv = windefs.ERROR_INSUFFICIENT_BUFFER
                else:
                    self.mem_write(lpData, output)

            # For now, return an empty buffer
            else:
                output = b'\x00' * length
                self.mem_write(lpData, output)
                rv = windefs.ERROR_SUCCESS

            kp = key.get_path()
            self.log_registry_access(kp, 'read_value', value_name=lpValue, size=length,
                                     buffer=lpData)

        return rv