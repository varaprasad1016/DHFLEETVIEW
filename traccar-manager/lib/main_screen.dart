import 'dart:async';
import 'dart:collection';
import 'dart:convert';
import 'dart:developer' as developer;
import 'dart:io';

import 'package:app_links/app_links.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_inappwebview/flutter_inappwebview.dart';
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:share_plus/share_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:shared_preferences_android/shared_preferences_android.dart';
import 'package:traccar_manager/error_screen.dart';
import 'package:traccar_manager/token_store.dart';
import 'package:url_launcher/url_launcher.dart';

class MainScreen extends StatefulWidget {
  const MainScreen({super.key});

  @override
  State<MainScreen> createState() => _MainScreenState();
}

class _MainScreenState extends State<MainScreen> {
  static const _urlKey = 'url';
  static const kDefaultUrl = 'https://dhfleetview.co.uk';

  final _initialized = Completer<void>();
  final _authenticated = Completer<void>();

  late final SharedPreferencesWithCache _preferences;
  late final AppLinks _appLinks;
  StreamSubscription<Uri>? _appLinksSubscription;
  final _loginTokenStore = TokenStore();
  InAppWebViewController? _controller;
  String? _loadingError;
  late String _initialUrl;
  bool _settingsReady = false;
  bool _controllerReady = false;

  @override
  void initState() {
    super.initState();
    _initWebView();
    _initAppLinks();
  }

  Future<void> _initAppLinks() async {
    await _initialized.future;
    _appLinks = AppLinks();
    _appLinksSubscription = _appLinks.uriLinkStream.listen((uri) {
      if (uri.scheme == 'com.dhgroup.fleetview') {
        final baseUri = Uri.parse(_getUrl());
        final appPathSegments = [uri.host, ...uri.pathSegments];
        final updatedQueryParameters = Map<String, String>.from(uri.queryParameters);
        if (uri.queryParameters.containsKey('code')) {
          updatedQueryParameters['redirect_uri'] = uri.toString().split('?').first;
        }
        final updatedUri = uri.replace(
          scheme: baseUri.scheme,
          host: baseUri.host,
          port: baseUri.port,
          path: '/${appPathSegments.join('/')}',
          queryParameters: updatedQueryParameters.isEmpty ? null : updatedQueryParameters,
        );
        _loadUrl(updatedUri);
      } else {
        _loadUrl(uri);
      }
    });
  }

  Future<void> _launchAuthorizeRequest(Uri uri) async {
    try {
      final originalRedirect = Uri.parse(uri.queryParameters['redirect_uri']!);
      final redirectSegments = originalRedirect.pathSegments;
      final updatedRedirect = Uri(
        scheme: 'com.dhgroup.fleetview',
        host: redirectSegments.first,
        path: '/${redirectSegments.skip(1).join('/')}',
        queryParameters: originalRedirect.queryParameters.isEmpty ? null : originalRedirect.queryParameters,
      );
      final updatedQueryParameters = Map<String, String>.from(uri.queryParameters)
        ..['redirect_uri'] = updatedRedirect.toString();
      await launchUrl(uri.replace(queryParameters: updatedQueryParameters), mode: LaunchMode.externalApplication);
    } catch (e) {
      developer.log('Failed to launch authorize request', error: e);
    }
  }

  @override
  void dispose() {
    _appLinksSubscription?.cancel();
    super.dispose();
  }

  String _getUrl() {
    // Saved server URL always takes precedence. First launch (or a saved
    // dev/emulator address) falls back to the production server.
    final saved = _preferences.getString(_urlKey);
    final url = saved ?? kDefaultUrl;
    return url.endsWith('/') ? url.substring(0, url.length - 1) : url;
  }

  bool _isDownloadable(Uri uri) {
    final path = uri.path.toLowerCase();
    final lastSegment = uri.pathSegments.isNotEmpty ? uri.pathSegments.last.toLowerCase() : '';
    const exts = ['xlsx', 'kml', 'csv', 'gpx', 'mp4', 'ddd', 'exe', 'pdf', 'zip', 'kmz'];
    return exts.contains(lastSegment)
        || exts.any((e) => lastSegment.endsWith('.$e'))
        || path.endsWith('/download')
        || path.contains('/download/');
  }

  Future<void> _shareFile(String fileName, Uint8List bytes) async {
    final directory = Platform.isAndroid
      ? await getExternalStorageDirectory()
      : await getApplicationDocumentsDirectory();
    if (directory == null) {
      throw StateError('No writable storage directory is available');
    }
    final file = File('${directory.path}/$fileName');
    await file.writeAsBytes(bytes, flush: true);
    await SharePlus.instance.share(ShareParams(files: [XFile(file.path)]));
  }

  /// Whether this address belongs to the server the app is signed in to.
  /// Used to decide what may be fetched with the session rather than handed
  /// to the phone's browser, which has none of it.
  bool _isOwnServer(Uri uri) {
    final saved = _preferences.getString(_urlKey);
    if (saved == null) return false;
    final base = Uri.tryParse(saved);
    return base != null
        && uri.host.isNotEmpty
        && uri.host.toLowerCase() == base.host.toLowerCase();
  }

  /// A name safe to write to disk, with an extension the sharing sheet can
  /// make sense of. The page supplies both, and neither can be trusted: the
  /// name may carry path separators, or be missing altogether.
  String _safeFileName(String name, String mimeType) {
    var safe = name.replaceAll(RegExp(r'[\\/:*?"<>|]'), '_').trim();
    if (safe.isEmpty || safe == '_') safe = 'download';
    if (!safe.contains('.')) {
      const byType = {
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'xlsx',
        'application/pdf': 'pdf',
        'text/csv': 'csv',
        'application/json': 'json',
        'application/zip': 'zip',
        'image/jpeg': 'jpg',
        'image/png': 'png',
        'video/mp4': 'mp4',
        'application/vnd.google-earth.kml+xml': 'kml',
      };
      final extension = byType[mimeType.split(';').first.trim().toLowerCase()];
      if (extension != null) safe = '$safe.$extension';
    }
    return safe;
  }

  String _fileNameFor(Uri uri, String? contentDisposition) {
    if (contentDisposition != null) {
      final encodedMatch = RegExp(r"filename\*=UTF-8''([^;]+)", caseSensitive: false)
        .firstMatch(contentDisposition);
      if (encodedMatch != null) {
        return Uri.decodeComponent(encodedMatch.group(1)!).trim();
      }
      final match = RegExp(r'filename="?([^";]+)"?', caseSensitive: false)
        .firstMatch(contentDisposition);
      if (match != null && match.group(1)!.trim().isNotEmpty) {
        return match.group(1)!.trim();
      }
    }
    final last = uri.pathSegments.isNotEmpty ? uri.pathSegments.last : 'download';
    if (last.contains('.')) return last;
    return '${DateTime.now().millisecondsSinceEpoch}_$last';
  }

  void _showDownloadMessage(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _downloadFile(Uri uri, {String? contentDisposition,
                                       String? suggestedFileName}) async {
    try {
      // The session the page is using lives in the WebView's cookies, not in
      // the stored token, and a /tacho page is signed in separately again.
      // Sending the cookies as well as the token means a download works
      // wherever in the app it was started, rather than only on the pages the
      // stored token happens to cover.
      final cookies = await CookieManager.instance().getCookies(url: WebUri.uri(uri));
      final headers = <String, String>{};
      if (cookies.isNotEmpty) {
        headers['Cookie'] = cookies.map((c) => '${c.name}=${c.value}').join('; ');
      }
      final token = await _loginTokenStore.read(false);
      if (token != null) headers['Authorization'] = 'Bearer $token';
      if (headers.isEmpty) {
        _showDownloadMessage('Please log in again before downloading a file.');
        return;
      }
      final response = await http.get(uri, headers: headers);
      if (response.statusCode >= 200 && response.statusCode < 300) {
        // Both routes end up here so that a file served without a name of its
        // own still gets an extension from what the server says it is. A
        // certificate sent inline has neither, and lands as "certificate" with
        // nothing to tell the phone how to open it.
        final name = suggestedFileName
          ?? _fileNameFor(uri, contentDisposition ?? response.headers['content-disposition']);
        await _shareFile(
          _safeFileName(name, response.headers['content-type'] ?? ''),
          response.bodyBytes,
        );
      } else {
        developer.log('Failed file download request: HTTP ${response.statusCode}');
        _showDownloadMessage('The file could not be downloaded (${response.statusCode}).');
      }
    } catch (e) {
      developer.log('Failed to download file', error: e);
      _showDownloadMessage('The file could not be downloaded. Please try again.');
    }
  }

  void _maybeCompleteInitialized() {
    if (!_initialized.isCompleted && _settingsReady && _controllerReady) {
      _initialized.complete();
    }
  }

  Future<void> _initWebView() async {
    _preferences = await SharedPreferencesWithCache.create(
      sharedPreferencesOptions: Platform.isAndroid
        ? SharedPreferencesAsyncAndroidOptions(backend: SharedPreferencesAndroidBackendLibrary.SharedPreferences)
        : SharedPreferencesOptions(),
      cacheOptions: SharedPreferencesWithCacheOptions(allowList: {'url'}),
    );

    final savedUrl = _preferences.getString(_urlKey);
    if (savedUrl != null
        && (savedUrl.startsWith('http://10.0.2.2')
            || savedUrl.startsWith('http://localhost')
            || savedUrl.startsWith('http://127.0.0.1'))) {
      await _preferences.setString(_urlKey, kDefaultUrl);
    }

    var url = _getUrl();

    setState(() {
      _initialUrl = url;
      _settingsReady = true;
    });

    _maybeCompleteInitialized();
  }

  void _handleWebMessage(String message) async {
    final List<String> parts = message.split('|');
    switch (parts[0]) {
      case 'login':
        if (parts.length > 1) {
          await _loginTokenStore.save(parts[1]);
        }
      case 'authentication':
        final loginToken = await _loginTokenStore.read(true);
        if (loginToken != null) {
          _controller?.evaluateJavascript(source: "handleLoginToken?.('$loginToken')");
        }
      case 'authenticated':
        if (!_authenticated.isCompleted) _authenticated.complete();
      case 'logout':
        await _loginTokenStore.delete();
      case 'download':
        // download|mime|name|base64 - a file the page built for itself.
        try {
          if (parts.length < 2) throw const FormatException('Missing download data');
          if (parts.length >= 4) {
            // The base64 is last and can itself contain nothing but base64
            // characters, so anything after the third separator is payload.
            await _shareFile(
              _safeFileName(parts[2], parts[1]),
              base64Decode(parts.sublist(3).join('|')),
            );
          } else {
            // The older two-part form, still sent by pages that have not been
            // through this path: a spreadsheet and nothing else.
            await _shareFile('report.xlsx', base64Decode(parts[1]));
          }
        } catch (e) {
          developer.log('Failed to save downloaded file', error: e);
          _showDownloadMessage('The file could not be saved. Please try again.');
        }
      case 'downloadUrl':
        // downloadUrl|suggested name|absolute url - a normal link carrying a
        // download attribute, which the WebView would otherwise just navigate.
        if (parts.length >= 3) {
          final target = Uri.tryParse(parts.sublist(2).join('|'));
          if (target != null && (target.scheme == 'http' || target.scheme == 'https')) {
            await _downloadFile(target,
              suggestedFileName: parts[1].isEmpty ? null : parts[1]);
          }
        }
      case 'server':
        final url = parts[1];
        await _loginTokenStore.delete();
        await _preferences.setString(_urlKey, url);
        await _loadUrl(Uri.parse(url));
    }
  }

  bool _isRootOrLogin(String baseUrl, String? currentUrl) {
    if (currentUrl == null) return false;
    final baseUri = Uri.parse(baseUrl);
    final currentUri = Uri.parse(currentUrl);
    if (baseUri.origin != currentUri.origin) return false;
    return currentUri.path == '/' || currentUri.path == '/login';
  }

  Future<void> _loadUrl(Uri uri) async {
    await _controller?.loadUrl(urlRequest: URLRequest(url: WebUri(uri.toString())));
  }

  Widget _buildLoadingScreen() {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(28),
            child: Image.asset(
              'assets/icon/icon.png',
              width: 96,
              height: 96,
            ),
          ),
          const SizedBox(height: 24),
          const Text(
            'DH FleetView',
            style: TextStyle(
              fontSize: 22,
              fontWeight: FontWeight.w700,
              letterSpacing: -0.3,
              color: Color(0xFF1E293B),
            ),
          ),
          const SizedBox(height: 6),
          const Text(
            'TRACKING AND LIVE VIEW',
            style: TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.w600,
              letterSpacing: 1.6,
              color: Color(0xFF64748B),
            ),
          ),
          const SizedBox(height: 28),
          const SizedBox(
            width: 28,
            height: 28,
            child: CircularProgressIndicator(
              strokeWidth: 3,
              color: Color(0xFF4F46E5),
            ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    if (!_settingsReady) {
      return _buildLoadingScreen();
    }
    if (_loadingError != null) {
      return ErrorScreen(
        error: _loadingError!,
        url: _getUrl(),
        onUrlSubmitted: (url) async {
          await _loginTokenStore.delete();
          await _preferences.setString(_urlKey, url);
          setState(() {
            _initialUrl = url;
            _loadingError = null;
            _controller = null;
            _controllerReady = false;
          });
        },
      );
    }
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, result) {
        if (didPop) return;
        _controller?.getUrl().then((url) {
          _controller?.canGoBack().then((canGoBack) {
            if (canGoBack == true && !_isRootOrLogin(_getUrl(), url?.toString())) {
              _controller?.goBack();
            } else {
              SystemNavigator.pop();
            }
          });
        });
      },
      child: Scaffold(
        resizeToAvoidBottomInset: false,
        body: SafeArea(
          maintainBottomViewPadding: true,
          child: InAppWebView(
            key: ValueKey(_initialUrl),
            initialUrlRequest: URLRequest(url: WebUri(_initialUrl)),
            initialSettings: InAppWebViewSettings(
              javaScriptEnabled: true,
              useShouldOverrideUrlLoading: true,
              // Without this, onDownloadStartRequest below is registered and
              // never called, so every download in the app did nothing at all.
              useOnDownloadStart: true,
              // Same again for onCreateWindow: on Android it is not called
              // unless multiple windows are supported, so every link that
              // opens in a new tab - a training certificate, a maintenance
              // document, a signature - did nothing whatsoever.
              supportMultipleWindows: true,
              javaScriptCanOpenWindowsAutomatically: true,
              supportZoom: false,
              builtInZoomControls: false,
            ),
            initialUserScripts: UnmodifiableListView<UserScript>([
              UserScript(
                source: '''
                  window.appInterface = {
                    postMessage: function(message) {
                      if (window.flutter_inappwebview && window.flutter_inappwebview.callHandler) {
                        window.flutter_inappwebview.callHandler('appInterface', message);
                      } else {
                        window.__traccarMessageQueue = window.__traccarMessageQueue || [];
                        window.__traccarMessageQueue.push(message);
                      }
                    }
                  };
                  (function() {
                    // Files the page builds itself never reach the WebView as a
                    // download: a spreadsheet export or a video snapshot is a
                    // blob: or data: link, often clicked by script on an anchor
                    // that was never put in the document. The WebView cancels
                    // those and nothing happens. They are read here instead and
                    // handed to the app as bytes.
                    if (window.__dhfvDownloads) return;
                    window.__dhfvDownloads = true;
                    var blobs = new Map();
                    var originalCreateObjectURL = URL.createObjectURL;
                    URL.createObjectURL = function(object) {
                      var url = originalCreateObjectURL.apply(this, arguments);
                      if (object instanceof Blob) blobs.set(url, object);
                      return url;
                    };
                    var clean = function(value) { return String(value || '').replace(/[|\\r\\n]/g, '_'); };
                    var post = function(message) { window.appInterface.postMessage(message); };
                    var sendBlob = function(blob, name) {
                      var reader = new FileReader();
                      reader.onload = function() {
                        post('download|' + clean(blob.type || 'application/octet-stream') + '|' + clean(name || 'download')
                          + '|' + String(reader.result).split(',')[1]);
                      };
                      reader.readAsDataURL(blob);
                    };
                    var handleInPage = function(href, name) {
                      if (href.indexOf('blob:') === 0) {
                        var blob = blobs.get(href);
                        if (blob) { sendBlob(blob, name); return true; }
                        fetch(href).then(function(r) { return r.blob(); }).then(function(b) { sendBlob(b, name); });
                        return true;
                      }
                      if (href.indexOf('data:') === 0) {
                        var match = /^data:([^;,]*)((?:;[^;,]*)*?)(;base64)?,([\\s\\S]*)\$/.exec(href);
                        if (!match) return false;
                        var b64 = match[3] ? match[4] : btoa(unescape(encodeURIComponent(decodeURIComponent(match[4]))));
                        post('download|' + clean(match[1] || 'application/octet-stream') + '|' + clean(name || 'download') + '|' + b64);
                        return true;
                      }
                      return false;
                    };
                    var handleAnchor = function(anchor) {
                      var href = anchor.href || '';
                      var name = anchor.getAttribute('download');
                      if (href.indexOf('blob:') === 0 || href.indexOf('data:') === 0) return handleInPage(href, name);
                      if (name !== null && /^https?:/.test(href)) { post('downloadUrl|' + clean(name) + '|' + href); return true; }
                      return false;
                    };
                    document.addEventListener('click', function(event) {
                      var anchor = event.target && event.target.closest ? event.target.closest('a[href]') : null;
                      if (anchor && handleAnchor(anchor)) { event.preventDefault(); event.stopImmediatePropagation(); }
                    }, true);
                    // Code-triggered downloads (file-saver and friends) click a
                    // link that is not in the page, so the listener above never
                    // sees them.
                    var originalClick = HTMLAnchorElement.prototype.click;
                    HTMLAnchorElement.prototype.click = function() {
                      if (handleAnchor(this)) return;
                      return originalClick.apply(this, arguments);
                    };
                    var originalDispatch = EventTarget.prototype.dispatchEvent;
                    EventTarget.prototype.dispatchEvent = function(event) {
                      if (event && event.type === 'click' && this instanceof HTMLAnchorElement && !this.isConnected && handleAnchor(this)) {
                        return false;
                      }
                      return originalDispatch.apply(this, arguments);
                    };
                    var originalOpen = window.open;
                    window.open = function(url) {
                      if (typeof url === 'string' && (url.indexOf('blob:') === 0 || url.indexOf('data:') === 0) && handleInPage(url, 'download')) {
                        return null;
                      }
                      return originalOpen.apply(this, arguments);
                    };
                  })();
                  const excelType = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
                  const originalCreateObjectURL = URL.createObjectURL;
                  URL.createObjectURL = function(object) {
                    if (object instanceof Blob && object.type === excelType) {
                      const reader = new FileReader();
                      reader.onload = () => {
                        window.appInterface.postMessage('download|' + reader.result.split(',')[1]);
                      };
                      reader.readAsDataURL(object);
                    }
                    return originalCreateObjectURL.apply(this, arguments);
                  };
                  window.addEventListener('flutterInAppWebViewPlatformReady', function() {
                    if (window.__traccarMessageQueue && window.flutter_inappwebview && window.flutter_inappwebview.callHandler) {
                      window.__traccarMessageQueue.forEach(function(message) {
                        window.flutter_inappwebview.callHandler('appInterface', message);
                      });
                      window.__traccarMessageQueue = [];
                    }
                  });
                ''',
                injectionTime: UserScriptInjectionTime.AT_DOCUMENT_START,
              ),
            ]),
            onWebViewCreated: (controller) {
              _controller = controller;
              controller.addJavaScriptHandler(
                handlerName: 'appInterface',
                callback: (args) {
                  if (args.isEmpty) return null;
                  _handleWebMessage(args.first.toString());
                  return null;
                },
              );
              _controllerReady = true;
              _maybeCompleteInitialized();
            },
            onLoadStart: (controller, url) {
              setState(() => _loadingError = null);
            },
            shouldOverrideUrlLoading: (controller, navigationAction) async {
              final target = navigationAction.request.url;
              if (target == null) {
                return NavigationActionPolicy.ALLOW;
              }
              final uri = Uri.parse(target.toString());
              if (['response_type', 'client_id', 'redirect_uri', 'scope'].every(uri.queryParameters.containsKey)) {
                _launchAuthorizeRequest(uri);
                return NavigationActionPolicy.CANCEL;
              }
              if (uri.scheme == 'blob' || uri.scheme == 'data') {
                // Blob/data downloads are delivered through the injected bridge.
                return NavigationActionPolicy.CANCEL;
              }
              if (_isDownloadable(uri)) {
                await _downloadFile(uri);
                return NavigationActionPolicy.CANCEL;
              }
              if (uri.authority != Uri.parse(_getUrl()).authority) {
                try {
                  await launchUrl(uri, mode: LaunchMode.externalApplication);
                } catch (e) {
                  developer.log('Failed to launch url', error: e);
                }
                return NavigationActionPolicy.CANCEL;
              }
              return NavigationActionPolicy.ALLOW;
            },
            onDownloadStartRequest: (controller, downloadStartRequest) async {
              final target = downloadStartRequest.url;
              await _downloadFile(
                Uri.parse(target.toString()),
                contentDisposition: downloadStartRequest.contentDisposition,
              );
            },
            onCreateWindow: (controller, createWindowAction) async {
              final target = createWindowAction.request.url;
              if (target == null) return false;
              final uri = Uri.parse(target.toString());
              // Anything on our own server is fetched here, where the session
              // is. Handing it to the phone's browser instead opens it with no
              // cookies at all, so a training certificate or a maintenance
              // document came back 401 and the link looked broken. These have
              // no file extension either, so the name is taken from what the
              // server says it is sending.
              if (_isOwnServer(uri) || _isDownloadable(uri)) {
                await _downloadFile(uri);
              } else {
                // A genuinely external link - a maps route for a job - belongs
                // in the app that handles it.
                await launchUrl(uri, mode: LaunchMode.externalApplication);
              }
              return false;
            },
            onReceivedError: (controller, request, error) {
              if (request.isForMainFrame == true) {
                final isInterruptedFrameLoad = Platform.isIOS && error.description.contains('code=102');
                if (error.type == WebResourceErrorType.CANCELLED || isInterruptedFrameLoad) {
                  return;
                }
                final errorMessage = error.description.isNotEmpty
                  ? error.description
                  : error.type.toString();
                setState(() => _loadingError = errorMessage);
              }
            },
            onRenderProcessGone: (controller, detail) async {
              await controller.reload();
            },
            onWebContentProcessDidTerminate: (controller) {
              controller.reload();
            },
            onGeolocationPermissionsShowPrompt: (controller, origin) async {
              final status = await Permission.location.request();
              return GeolocationPermissionShowPromptResponse(
                origin: origin,
                allow: status.isGranted,
                retain: true,
              );
            },
            onPermissionRequest: (controller, request) async {
              var allGranted = true;
              for (final resource in request.resources) {
                PermissionStatus status;
                final resourceUpper = resource.toString().toUpperCase();
                if (resourceUpper.contains('VIDEO_CAPTURE') || resourceUpper.contains('CAMERA')) {
                  status = await Permission.camera.request();
                } else {
                  allGranted = false;
                  continue;
                }
                if (!status.isGranted) allGranted = false;
              }
              return PermissionResponse(
                resources: request.resources,
                action: allGranted
                  ? PermissionResponseAction.GRANT
                  : PermissionResponseAction.DENY,
              );
            },
          ),
        ),
      ),
    );
  }
}
