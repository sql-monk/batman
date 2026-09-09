import pcbnew


def point(x, y):
    return pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y))


def track(board, net, start, end, width):
    segment = pcbnew.PCB_TRACK(board)
    segment.SetStart(point(*start))
    segment.SetEnd(point(*end))
    segment.SetWidth(pcbnew.FromMM(width))
    segment.SetLayer(pcbnew.B_Cu)
    segment.SetNet(board.FindNet(net))
    board.Add(segment)


def outline(board, x, y, width, height):
    corners = [(x, y), (x + width, y), (x + width, y + height), (x, y + height)]
    for start, end in zip(corners, corners[1:] + corners[:1]):
        edge = pcbnew.PCB_SHAPE()
        edge.SetShape(pcbnew.SHAPE_T_SEGMENT)
        edge.SetStart(point(*start))
        edge.SetEnd(point(*end))
        edge.SetLayer(pcbnew.Edge_Cuts)
        edge.SetWidth(pcbnew.FromMM(0.05))
        board.Add(edge)


def set_lut_rules(board):
    settings = board.GetDesignSettings()
    settings.m_MinClearance = pcbnew.FromMM(0.5)
    settings.m_TrackMinWidth = pcbnew.FromMM(0.7)
    settings.m_CopperEdgeClearance = pcbnew.FromMM(0.5)
    default = settings.m_NetSettings.GetDefaultNetclass()
    default.SetClearance(pcbnew.FromMM(0.5))
    default.SetTrackWidth(pcbnew.FromMM(0.7))


def new_board(names):
    board = pcbnew.BOARD()
    board.SetCopperLayerCount(2)
    set_lut_rules(board)
    for name in names:
        board.Add(pcbnew.NETINFO_ITEM(board, name))
    return board