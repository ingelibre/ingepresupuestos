import QtQuick
import QtQuick3D

// Escena 3D del visor BIM. Python (views/bim_visor.py) entrega las mallas con
// agregarBloque() y la paleta con ponerPaletas(): una textura de un texel por
// «parte» del modelo, que decide color, transparencia y visibilidad.
Item {
    id: root

    property color fondo: "#EEF1F4"
    property real yaw: -35
    property real pitch: 28
    property real distancia: 20
    property vector3d objetivo: Qt.vector3d(0, 0, 0)
    property real radio: 10          // del modelo: fija los planos de corte
    property bool hayTransparentes: false
    property int fotogramas: 0       // para medir fps

    // Rayo en coordenadas de la escena; lo resuelve Python.
    signal tocado(vector3d origen, vector3d direccion, bool sumar)

    function agregarBloque(geo) {
        fabrica.createObject(nodo, { geometry: geo, materials: [opaco] })
        fabrica.createObject(nodoTransparente, { geometry: geo, materials: [vidrio] })
    }
    function vaciar() {
        for (var n of [nodo, nodoTransparente])
            for (var i = n.children.length - 1; i >= 0; --i)
                n.children[i].destroy()
    }
    function ponerPaletas(solida, transparente) {
        texSolida.textureData = solida
        texTransparente.textureData = transparente
    }
    function encuadrar(centro, r) {
        objetivo = centro
        // que la esfera entre en el lado más corto de la ventana
        var medio = camara.fieldOfView * Math.PI / 360
        if (width < height)
            medio = Math.atan(Math.tan(medio) * width / Math.max(1, height))
        distancia = Math.max(0.2, 0.85 * r / Math.sin(medio))
    }
    function vista(y, p) { yaw = y; pitch = p }

    View3D {
        id: escena
        anchors.fill: parent
        camera: camara
        environment: SceneEnvironment {
            backgroundMode: SceneEnvironment.Color
            clearColor: root.fondo
            antialiasingMode: SceneEnvironment.MSAA
            antialiasingQuality: SceneEnvironment.Medium
        }

        Node {
            position: root.objetivo
            eulerRotation: Qt.vector3d(-root.pitch, root.yaw, 0)
            PerspectiveCamera {
                id: camara
                z: root.distancia
                fieldOfView: 45
                clipNear: Math.max(0.02, (root.distancia - 2.2 * root.radio) * 0.5,
                                   root.distancia / 500)
                clipFar: root.distancia + 4 * root.radio + 10
                // luz de frente, pegada a la cámara
                DirectionalLight { brightness: 0.55; eulerRotation: Qt.vector3d(-15, 20, 0) }
            }
        }
        DirectionalLight {
            eulerRotation: Qt.vector3d(-55, -40, 0)
            brightness: 0.65
            ambientColor: Qt.rgba(0.42, 0.42, 0.44, 1)
        }

        Node { id: nodo }
        Node { id: nodoTransparente; visible: root.hayTransparentes }
    }

    Component {
        id: fabrica
        Model { pickable: false }
    }

    Texture {
        id: texSolida
        magFilter: Texture.Nearest
        minFilter: Texture.Nearest
        mipFilter: Texture.None
        generateMipmaps: false
    }
    Texture {
        id: texTransparente
        magFilter: Texture.Nearest
        minFilter: Texture.Nearest
        mipFilter: Texture.None
        generateMipmaps: false
    }
    PrincipledMaterial {
        id: opaco
        baseColorMap: texSolida
        alphaMode: PrincipledMaterial.Mask
        alphaCutoff: 0.5
        metalness: 0
        roughness: 0.85
        specularAmount: 0.15
        cullMode: Material.NoCulling    // hay IFC con caras al revés
    }
    PrincipledMaterial {
        id: vidrio
        baseColorMap: texTransparente
        alphaMode: PrincipledMaterial.Blend
        metalness: 0
        roughness: 0.6
        specularAmount: 0.15
        cullMode: Material.NoCulling
    }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.MiddleButton | Qt.RightButton
        property real x0: 0
        property real y0: 0
        property bool movido: false
        onPressed: (m) => { x0 = m.x; y0 = m.y; movido = false }
        onPositionChanged: (m) => {
            var dx = m.x - x0, dy = m.y - y0
            if (!movido && Math.abs(dx) + Math.abs(dy) < 5)
                return
            movido = true
            x0 = m.x; y0 = m.y
            var panear = (m.buttons & (Qt.MiddleButton | Qt.RightButton))
                         || (m.modifiers & Qt.ShiftModifier)
            if (panear) {
                var k = 2 * root.distancia
                        * Math.tan(camara.fieldOfView * Math.PI / 360) / root.height
                var d = camara.right.times(-dx * k).plus(camara.up.times(dy * k))
                root.objetivo = root.objetivo.plus(d)
            } else {
                root.yaw -= dx * 0.4
                root.pitch = Math.max(-89, Math.min(89, root.pitch + dy * 0.4))
            }
        }
        onReleased: (m) => {
            if (movido || m.button !== Qt.LeftButton)
                return
            root.tocarEn(m.x, m.y, (m.modifiers & Qt.ControlModifier) !== 0)
        }
        onDoubleClicked: (m) => root.doble()
        onWheel: (w) => {
            var f = Math.pow(0.999, w.angleDelta.y)
            root.distancia = Math.max(0.2, Math.min(root.radio * 20, root.distancia * f))
        }
    }
    signal doble()

    function tocarEn(x, y, sumar) {
        var a = escena.mapTo3DScene(Qt.vector3d(x, y, 0))
        var b = escena.mapTo3DScene(Qt.vector3d(x, y, root.distancia))
        root.tocado(a, b.minus(a).normalized(), sumar)
    }
    // Dónde cae un punto de la escena en la ventana (para los tests)
    function enPantalla(p) { return escena.mapFrom3DScene(p) }
}
